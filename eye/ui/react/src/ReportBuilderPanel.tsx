/**
 * Report Builder Panel Component for EYE Forensic Assistant
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
import ReportBlockComponent from './ReportBlockComponent';
import './ReportBuilderPanel.css';

/**
 * Report block types matching Python backend
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
  datasets: { label: string; data: number[] }[];
}

type AnyBlock = TextBlock | TableBlock | ImageBlock | ReferenceBlock | ChatBlock | ChartBlock;

/**
 * Report state structure from Python backend
 */
interface ReportState {
  blocks: AnyBlock[];
  edit_history: any[];
  metadata: {
    block_count: number;
    last_modified: string;
  };
}

/**
 * Export format types
 */
type ExportFormat = 'html' | 'pdf' | 'markdown';

/**
 * Main Report Builder Panel Component
 */
const ReportBuilderPanel: React.FC = () => {
  const [blocks, setBlocks] = useState<AnyBlock[]>([]);
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

  /**
   * Render main report builder interface
   */
  return (
    <div className="report-builder-panel">
      {/* Toolbar */}
      <div className="report-toolbar">
        <div className="toolbar-left">
          <h2 className="report-title">Forensic Investigation Report</h2>
          <div className="report-meta">
            <span className="block-count">{blocks.length} blocks</span>
            <span className="separator">•</span>
            <span className="last-updated">
              Last updated: {new Date(lastModified).toLocaleString()}
            </span>
          </div>
        </div>
        
        <div className="toolbar-right">
          <button
            onClick={() => handleExport('html')}
            disabled={isExporting || blocks.length === 0}
            className="export-button export-html"
            title="Export as HTML"
          >
            <span className="button-icon">📄</span>
            HTML
          </button>
          
          <button
            onClick={() => handleExport('pdf')}
            disabled={isExporting || blocks.length === 0}
            className="export-button export-pdf"
            title="Export as PDF"
          >
            <span className="button-icon">📑</span>
            PDF
          </button>
          
          <button
            onClick={() => handleExport('markdown')}
            disabled={isExporting || blocks.length === 0}
            className="export-button export-markdown"
            title="Export as Markdown"
          >
            <span className="button-icon">📝</span>
            Markdown
          </button>
        </div>
      </div>

      {/* Error banner */}
      {error && (
        <div className="error-banner">
          <span className="error-icon">⚠️</span>
          {error}
          <button onClick={() => setError(null)} className="dismiss-button">
            ✕
          </button>
        </div>
      )}

      {/* Success banner */}
      {successMessage && (
        <div className="success-banner">
          <span className="success-icon">✅</span>
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
            <div className="empty-icon">📋</div>
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
              <div className="blocks-container">
                {blocks.map((block) => (
                  <ReportBlockComponent
                    key={block.block_id}
                    block={block}
                    onDelete={handleBlockDelete}
                    onUpdate={handleBlockUpdate}
                  />
                ))}
              </div>
            </SortableContext>
          </DndContext>
        )}
      </div>
    </div>
  );
};

export default ReportBuilderPanel;
