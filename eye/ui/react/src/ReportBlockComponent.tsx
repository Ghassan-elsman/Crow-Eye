/**
 * Report Block Component for EYE Forensic Assistant
 * 
 * Individual block rendering with inline editing capabilities for each block type.
 * Includes category-based styling for consistent forensic pillars.
 */

import React, { useState, useEffect, useRef } from 'react';
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
}

// --- Helpers ---

/**
 * Maps forensic categories or keywords to consistent UI colors.
 */
const getCategoryColor = (category?: string, title: string = "", index: number = 0) => {
  const c = category?.toLowerCase() || '';
  const t = title.toLowerCase();

  // Priority 1: Explicit Category Mapping
  if (c === 'security') return '#ec4899'; // Security - Pink
  if (c === 'execution') return '#10b981'; // Execution - Green
  if (c === 'persistence') return '#8b5cf6'; // Persistence - Purple
  if (c === 'identity') return '#06b6d4'; // Identity - Cyan
  if (c === 'hardware') return '#f97316'; // Hardware - Orange
  if (c === 'filesystem') return '#ef4444'; // FileSystem - Red
  if (c === 'intent') return '#f59e0b'; // Intent - Amber
  if (c === 'evidence') return '#8b5cf6'; // Evidence - Purple

  // Priority 2: Keyword Fallback
  if (t.includes('security') || t.includes('auth') || t.includes('logon') || t.includes('remote')) return '#ec4899';
  if (t.includes('execution') || t.includes('prefetch') || t.includes('amcache') || t.includes('app')) return '#10b981';
  if (t.includes('persistence') || t.includes('run') || t.includes('service') || t.includes('startup')) return '#8b5cf6';
  if (t.includes('identity') || t.includes('user') || t.includes('account')) return '#06b6d4';
  if (t.includes('usb') || t.includes('hardware') || t.includes('device')) return '#f97316';
  if (t.includes('file') || t.includes('mft') || t.includes('usn') || t.includes('recycle')) return '#ef4444';
  if (t.includes('intent') || t.includes('lnk') || t.includes('recent')) return '#f59e0b';
  
  // Default palette if no match
  const palette = ['#f97316', '#06b6d4', '#ec4899', '#10b981', '#ff4d6a', '#8b5cf6'];
  return palette[index % palette.length];
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
      <h3 className="text-block-title" style={{ color: getCategoryColor(block.category, block.title) }}>{block.title}</h3>
      <div className="text-block-content">{block.markdown_content.split('\n').map((l, i) => <p key={i}>{l}</p>)}</div>
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

const ChartBlockContent: React.FC<{ block: ChartBlock }> = ({ block }) => {
  const chartRef = useRef<any>(null);

  // Force reflow after initial render to fix alignment issues
  useEffect(() => {
    const timer = setTimeout(() => {
      if (chartRef.current) {
        chartRef.current.update();
      }
    }, 300);

    // Also listen for global reflow event from bridge
    const handleReflow = () => {
      if (chartRef.current) {
        chartRef.current.update();
      }
    };

    window.addEventListener('reflow-forensic-charts', handleReflow);
    return () => {
      clearTimeout(timer);
      window.removeEventListener('reflow-forensic-charts', handleReflow);
    };
  }, []);

  // If backend provided a pre-rendered Chart.js config, use it directly
  if (block.metadata.chart_config) {
    const config = block.metadata.chart_config;
    return (
      <div className="chart-block-view">
        <div className="chart-container">
          {config.type === 'bar' && <Bar ref={chartRef} data={config.data} options={config.options} />}
          {config.type === 'line' && <Line ref={chartRef} data={config.data} options={config.options} />}
          {config.type === 'pie' && <Pie ref={chartRef} data={config.data} options={config.options} />}
          {config.type === 'doughnut' && <Pie ref={chartRef} data={config.data} options={{...config.options, cutout: '50%'}} />}
        </div>
      </div>
    );
  }

  // Fallback to local rendering for manual/legacy blocks
  const themeColor = getCategoryColor(block.category, block.title);

  const data = {
    labels: block.labels,
    datasets: block.datasets.map((ds, i) => ({
      ...ds,
      backgroundColor: ds.backgroundColor || getCategoryColor(block.category, block.title, i),
      borderColor: ds.borderColor || getCategoryColor(block.category, block.title, i),
      borderWidth: 1,
    }))
  };

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { 
        position: 'bottom' as const,
        labels: { 
          color: '#8899aa', 
          font: { family: 'Space Mono', size: 10 },
          boxWidth: 12,
          padding: 15
        } 
      },
      title: { 
        display: true, 
        text: block.title, 
        color: themeColor, 
        font: { size: 14, family: 'Syne', weight: 'bold' as const },
        padding: { bottom: 20 }
      },
      tooltip: {
        backgroundColor: '#1c2330',
        titleFont: { family: 'Syne' },
        bodyFont: { family: 'Space Mono' },
        borderColor: themeColor,
        borderWidth: 1
      }
    },
    scales: block.chart_type !== 'pie' ? {
      y: { 
        ticks: { color: '#4a5a6a', font: { size: 10 } }, 
        grid: { color: 'rgba(30, 42, 58, 0.5)' } 
      },
      x: { 
        ticks: { color: '#4a5a6a', font: { size: 10 } }, 
        grid: { display: false } 
      }
    } : undefined
  };

  return (
    <div className="chart-block-view">
      <div className="chart-container">
        {block.chart_type === 'bar' && <Bar ref={chartRef} data={data} options={options} />}
        {block.chart_type === 'line' && <Line ref={chartRef} data={data} options={options} />}
        {block.chart_type === 'pie' && <Pie ref={chartRef} data={data} options={options} />}
      </div>
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

const TimelineBlockContent: React.FC<{ block: TimelineBlock }> = ({ block }) => {
  const themeColor = getCategoryColor(block.category, block.title);
  return (
    <div className="timeline-block-view">
      <h4 style={{ color: themeColor }}>{block.title}</h4>
      <div className="timeline-list">
        {block.events.map((ev, i) => (
          <div key={i} className="timeline-item" style={{ borderLeftColor: getCategoryColor(ev.category || block.category, ev.label) }}>
            <span className="timeline-time">{new Date(ev.timestamp).toLocaleString()}</span>
            <span className="timeline-label">{ev.label}</span>
            <p className="timeline-desc">{ev.description}</p>
          </div>
        ))}
      </div>
    </div>
  );
};

const HeatmapBlockContent: React.FC<{ block: HeatmapBlock }> = ({ block }) => {
  return (
    <div className="heatmap-block-view">
      <h4>{block.title}</h4>
      <div className="heatmap-grid" style={{ gridTemplateColumns: `repeat(${block.x_labels.length}, 1fr)` }}>
        {block.intensity_values.flat().map((v, i) => (
          <div key={i} className="heatmap-cell" style={{ opacity: v / 10, background: '#f97316' }} title={`Value: ${v}`} />
        ))}
      </div>
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
        <div className="chat-bubble-content">
          {msg.content.split('\n').map((line, i) => <React.Fragment key={i}>{line}<br/></React.Fragment>)}
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

  const themeColor = getCategoryColor(block.category, (block as any).title || (block as any).caption || (block as any).reference_text);

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
      style={{ ...style, ['--block-accent' as any]: themeColor }}
      className={`report-block ${block.block_type}-block ${isDragging ? 'dragging' : ''}`}
      {...attributes}
    >
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
