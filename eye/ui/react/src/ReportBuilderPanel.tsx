/**
 * Report Builder Panel Component for Eye Forensic Assistant
 * 
 * Interactive report builder workspace that allows investigators to create and
 * manipulate forensic reports with drag-and-drop block reordering. Supports
 * collaborative editing between AI and investigator.
 * 
 */

import React, { useState, useEffect } from 'react';
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core';
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { initializeBridge, onReportUpdated, getBridge } from './bridge';
import ReportBlockComponent, { KIND_NAMES, severityTone } from './ReportBlockComponent';
import ErrorBoundary from './ErrorBoundary';
import { IconFileText, IconDownload, IconClipboardList, IconAlertTriangle, IconCircleCheck } from './Icons';
import './ReportBuilderPanel.css';


import type { AnyBlock } from './types';

/**
 * Report state structure from Python backend
 */
interface ReportState {
  blocks: AnyBlock[];
  edit_history: any[];
  metadata: {
    block_count: number;
    last_modified: string;
    case?: CaseFacts;
  };
}

/** What the report can state about its case (ReportEngine.case_facts). */
interface CaseFacts {
  case_name?: string;
  case_number?: string;
  investigation_reason?: string;
  investigation_objectives?: string;
  investigator_name?: string;
  generated_utc?: string;
  sections?: Record<string, number>;
}

const COMPACT_CHARTS = new Set(['pie', 'doughnut', 'radar', 'polarArea']);

const blockTitle = (b: AnyBlock): string => {
  const x = b as any;
  const t = String(x.title || x.caption || '').trim();
  if (t) return t;
  if (b.block_type === 'reference') return String(x.reference_text || '').split('\n')[0].slice(0, 90) || 'Evidence';
  return KIND_NAMES[b.block_type] || 'Section';
};

/** Plain first sentence of a finding's markdown, for the findings strip. */
const firstSentence = (md: string, limit = 170): string => {
  const text = (md || '').replace(/\*+|__|`/g, '').replace(/[#>|]+/g, ' ')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1').replace(/\s+/g, ' ').trim();
  const m = (text + ' ').match(/^(.{20,}?[.!?])\s/);
  const out = m ? m[1] : text;
  return out.length <= limit ? out : out.slice(0, limit - 1).trimEnd() + '\u2026';
};

/** Two small charts next to each other share a row (wide screens): greedy, in order. */
const pairLayouts = (blocks: AnyBlock[]): Array<'full' | 'half'> => {
  const compact = blocks.map((b) => b.block_type === 'chart' && COMPACT_CHARTS.has((b as any).chart_type));
  const out: Array<'full' | 'half'> = blocks.map(() => 'full');
  for (let i = 0; i + 1 < blocks.length; i++) {
    if (compact[i] && compact[i + 1]) { out[i] = 'half'; out[i + 1] = 'half'; i++; }
  }
  return out;
};

/**
 * Export format types
 */
type ExportFormat = 'html' | 'pdf' | 'markdown';

/**
 * Main Report Builder Panel Component
 */
const ReportBuilderPanel: React.FC = () => {
  const [blocks, setBlocks] = useState<AnyBlock[]>([]);
  const [caseFacts, setCaseFacts] = useState<CaseFacts | null>(null);
  const [lastModified, setLastModified] = useState<string>('');
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [isExporting, setIsExporting] = useState<boolean>(false);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  // Configure drag-and-drop sensors
  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );

  /**
   * Load initial report state from Python backend
   */
  const loadReportState = async () => {
    try {
      setIsLoading(true);
      setError(null);

      const bridge = getBridge();
      if (!bridge) {
        throw new Error('Bridge not initialized');
      }

      const responseJson = await bridge.get_report_state();
      const response: { success: boolean; data: ReportState; error: string | null } = JSON.parse(responseJson);

      if (response.success && response.data) {
        const reportData = response.data;
        setBlocks(reportData.blocks);
        setLastModified(reportData.metadata.last_modified);
        setCaseFacts(reportData.metadata.case || null);
        console.log(`Loaded report with ${reportData.blocks.length} blocks`);
      } else {
        throw new Error(response.error || 'Failed to parse report data');
      }
    } catch (err) {
      console.error('Failed to load report state:', err);
      setError(err instanceof Error ? err.message : 'Failed to load report');
    } finally {
      setIsLoading(false);
    }
  };

  /**
   * Initialize bridge and load report state on mount
   */
  useEffect(() => {
    const init = async () => {
      try {
        await initializeBridge();
        await loadReportState();
      } catch (err) {
        console.error('Failed to initialize report builder:', err);
        setError('Failed to connect to backend');
        setIsLoading(false);
      }
    };

    init();
  }, []);

  /**
   * Listen for report_updated signal from Python bridge
   */
  useEffect(() => {
    const handleUpdate = (reportJson: string) => {
      try {
        const parsed = JSON.parse(reportJson);
        
        // Handle both wrapped {success: true, data: ReportState} and raw ReportState formats
        const reportData = parsed.success !== undefined && parsed.data ? parsed.data : parsed;
        
        if (reportData && reportData.blocks) {
          setBlocks(reportData.blocks);
          if (reportData.metadata) {
            setLastModified(reportData.metadata.last_modified);
            if (reportData.metadata.case) setCaseFacts(reportData.metadata.case);
          }
          console.log('Report updated from backend');
        }
      } catch (err) {
        console.error('Failed to parse report update:', err);
      }
    };

    // 1. Official Bridge Signal
    const unsubscribe = onReportUpdated(handleUpdate);

    return () => {
      unsubscribe();
    };
  }, []);

  /**
   * Handle drag end event for block reordering
   */
  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;

    if (over && active.id !== over.id) {
      setBlocks((items) => {
        const oldIndex = items.findIndex((item) => item.block_id === active.id);
        const newIndex = items.findIndex((item) => item.block_id === over.id);

        const reorderedBlocks = arrayMove(items, oldIndex, newIndex);
        
        // TODO: Notify backend of reordering
        console.log(`Reordered block ${active.id} from ${oldIndex} to ${newIndex}`);
        
        return reorderedBlocks;
      });
    }
  };

  /**
   * Handle export button click
   */
  const handleExport = async (format: ExportFormat) => {
    try {
      setIsExporting(true);
      setError(null);
      setSuccessMessage(null);

      const bridge = getBridge();
      if (!bridge) {
        throw new Error('Bridge not initialized');
      }

      const responseJson = await bridge.export_report(format);
      const response = JSON.parse(responseJson);

      if (response.success) {
        const formatLabel = format.toUpperCase();
        setSuccessMessage(`Report exported successfully as ${formatLabel} to ${response.file_path}`);
        console.log(`Report exported to ${format}: ${response.file_path}`);
      } else {
        throw new Error(response.error || 'Export failed');
      }
    } catch (err) {
      console.error(`Failed to export report as ${format}:`, err);
      setError(err instanceof Error ? err.message : 'Export failed');
    } finally {
      setIsExporting(false);
    }
  };

  /**
   * Handle block deletion
   */
  const handleBlockDelete = (blockId: string) => {
    setBlocks((prevBlocks) => prevBlocks.filter((block) => block.block_id !== blockId));
  };

  /**
   * Handle block update
   */
  const handleBlockUpdate = (blockId: string, updatedBlock: AnyBlock) => {
    setBlocks((prevBlocks) =>
      prevBlocks.map((block) => (block.block_id === blockId ? updatedBlock : block))
    );
  };

  /**
   * Render loading state
   */
  if (isLoading) {
    return (
      <div className="report-builder-panel">
        <div className="loading-state">
          <div className="spinner"></div>
          <p>Loading report...</p>
        </div>
      </div>
    );
  }

  /**
   * Render error state
   */
  if (error && blocks.length === 0) {
    return (
      <div className="report-builder-panel">
        <div className="error-state">
          <p className="error-message">{error}</p>
          <button onClick={loadReportState} className="retry-button">
            Retry
          </button>
        </div>
      </div>
    );
  }

  const layouts = pairLayouts(blocks);
  const findings = blocks
    .map((b, i) => ({ b, n: i + 1 }))
    .filter(({ b }) => b.block_type === 'text' && String((b as any).title || '').trim());
  const jump = (n: number) => {
    const el = document.getElementById(`sec-${n}`);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };
  const facts: Array<[string, string]> = [];
  if (caseFacts) {
    facts.push(['Case', caseFacts.case_number || caseFacts.case_name || '-']);
    if (caseFacts.investigation_reason) facts.push(['Reason', caseFacts.investigation_reason]);
    if (caseFacts.investigator_name) facts.push(['Investigator', caseFacts.investigator_name]);
  }
  const kinds = Object.entries(caseFacts?.sections || {});
  if (kinds.length) {
    facts.push(['Sections', kinds.map(([k, n]) => `${n} ${(KIND_NAMES[k] || k).toLowerCase()}${n !== 1 ? 's' : ''}`).join(', ')]);
  }

  /**
   * Render main report builder interface
   */
  return (
    <div className="report-builder-panel">
      {/* Toolbar */}
      <div className="report-toolbar">
        <div className="toolbar-left">
          <div className="report-eyebrow">
            <IconClipboardList size={11} />
            <span>Crow-Eye / Forensic Output</span>
          </div>
          <h2 className="report-title">Forensic Investigation Report</h2>
          {facts.length > 0 && (
            <dl className="report-facts">
              {facts.map(([k, v]) => (
                <div className="report-fact" key={k}><dt>{k}</dt><dd title={v}>{v}</dd></div>
              ))}
            </dl>
          )}
          <div className="report-meta">
            <span className={`status-pill ${blocks.length === 0 ? 'is-empty' : 'is-active'}`}>
              <span className="status-dot" />
              {blocks.length === 0 ? 'Awaiting evidence' : 'Live'}
            </span>
            <span className="block-count">{blocks.length} {blocks.length === 1 ? 'block' : 'blocks'}</span>
            {lastModified && (
              <>
                <span className="separator">•</span>
                <span className="last-updated">
                  Last updated {new Date(lastModified).toLocaleString()}
                </span>
              </>
            )}
          </div>
        </div>

        <div className="toolbar-right export-group" role="group" aria-label="Export the report">
          <button
            onClick={() => handleExport('html')}
            disabled={isExporting || blocks.length === 0}
            className="export-button export-html"
            title="Export as HTML"
          >
            <IconFileText size={13} />
            <span>HTML</span>
          </button>

          <button
            onClick={() => handleExport('pdf')}
            disabled={isExporting || blocks.length === 0}
            className="export-button export-pdf"
            title="Export as PDF"
          >
            <IconDownload size={13} />
            <span>PDF</span>
          </button>

          <button
            onClick={() => handleExport('markdown')}
            disabled={isExporting || blocks.length === 0}
            className="export-button export-markdown"
            title="Export as Markdown"
          >
            <IconFileText size={13} />
            <span>Markdown</span>
          </button>
        </div>
      </div>

      {/* Error banner */}
      {error && (
        <div className="error-banner">
          <span className="error-icon"><IconAlertTriangle size={16} /></span>
          {error}
          <button onClick={() => setError(null)} className="dismiss-button">
            ✕
          </button>
        </div>
      )}

      {/* Success banner */}
      {successMessage && (
        <div className="success-banner">
          <span className="success-icon"><IconCircleCheck size={16} /></span>
          {successMessage}
          <button onClick={() => setSuccessMessage(null)} className="dismiss-button">
            ✕
          </button>
        </div>
      )}

      {/* Report content with drag-and-drop */}
      <div className="report-content">
        {blocks.length === 0 ? (
          <div className="empty-state">
            <div className="empty-icon"><IconClipboardList size={40} /></div>
            <h3>No report blocks yet</h3>
            <p>
              Ask the AI assistant to add findings to the report, or start
              building your report manually.
            </p>
          </div>
        ) : (
          <DndContext
            sensors={sensors}
            collisionDetection={closestCenter}
            onDragEnd={handleDragEnd}
          >
            <SortableContext
              items={blocks.map((block) => block.block_id)}
              strategy={verticalListSortingStrategy}
            >
              <div className="report-layout">
                <nav className="report-rail" aria-label="Contents">
                  <div className="rail-title">Contents</div>
                  <ol>
                    {blocks.map((b, i) => {
                      const tone = severityTone((b.metadata as any)?.severity);
                      return (
                        <li key={b.block_id}>
                          <button type="button" onClick={() => jump(i + 1)} title={blockTitle(b)}>
                            <span className="rail-num" style={tone ? { color: tone } : undefined}>{i + 1}</span>
                            <span className="rail-text">{blockTitle(b)}</span>
                          </button>
                        </li>
                      );
                    })}
                  </ol>
                </nav>
                <div className="report-main">
                  {findings.length > 0 && (
                    <section className="findings-strip" aria-label="Key findings">
                      <div className="strip-title">Key findings</div>
                      <ol>
                        {findings.map(({ b, n }) => {
                          const tone = severityTone((b.metadata as any)?.severity);
                          return (
                            <li key={b.block_id}>
                              <button type="button" onClick={() => jump(n)}
                                      style={tone ? { ['--finding-tone' as any]: tone } : undefined}
                                      className={tone ? 'has-severity' : ''}>
                                <span className="finding-num">{n}</span>
                                <span className="finding-text">
                                  <strong>{(b as any).title}</strong>
                                  <span>{firstSentence((b as any).markdown_content || '')}</span>
                                </span>
                              </button>
                            </li>
                          );
                        })}
                      </ol>
                    </section>
                  )}
                  <div className="blocks-container">
                    {blocks.map((block, i) => (
                      <ErrorBoundary key={block.block_id} componentName={`Report Block (${block.block_type})`}>
                        <ReportBlockComponent
                          block={block}
                          sectionNumber={i + 1}
                          layout={layouts[i]}
                          onDelete={handleBlockDelete}
                          onUpdate={handleBlockUpdate}
                        />
                      </ErrorBoundary>
                    ))}
                  </div>
                </div>
              </div>
            </SortableContext>
          </DndContext>
        )}
      </div>
    </div>
  );
};

export default ReportBuilderPanel;
