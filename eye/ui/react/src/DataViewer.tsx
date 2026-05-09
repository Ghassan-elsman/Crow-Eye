import { useState, useMemo } from 'react';
import type { DataViewerProps } from './types';
import './DataViewer.css';

const DataViewer: React.FC<DataViewerProps> = ({ 
  columns, 
  rows, 
  query, 
  database, 
  table 
}) => {
  const [sortColumn, setSortColumn] = useState<string | null>(null);
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('asc');
  const [filterText, setFilterText] = useState('');
  const [currentPage, setCurrentPage] = useState(1);
  const rowsPerPage = 50;

  // Helper function to detect if a value is a file path
  const isFilePath = (value: unknown): boolean => {
    if (typeof value !== 'string') return false;
    // Windows path patterns: C:\, \\server\, or contains backslashes
    return /^[A-Za-z]:\\/.test(value) || 
           /^\\\\/.test(value) || 
           (value.includes('\\') && value.length > 3);
  };

  // Helper function to detect if a value is a timestamp
  const isTimestamp = (value: unknown, columnName: string): boolean => {
    if (typeof value !== 'string' && typeof value !== 'number') return false;
    
    // Check column name for timestamp indicators
    const timestampColumns = ['timestamp', 'time', 'date', 'created', 'modified', 'accessed', 'last_run'];
    if (timestampColumns.some(keyword => columnName.toLowerCase().includes(keyword))) {
      return true;
    }
    
    // Check if value looks like ISO 8601 or common timestamp formats
    if (typeof value === 'string') {
      // ISO 8601: YYYY-MM-DD HH:MM:SS or YYYY-MM-DDTHH:MM:SS
      return /^\d{4}-\d{2}-\d{2}[\sT]\d{2}:\d{2}:\d{2}/.test(value);
    }
    
    return false;
  };

  // Helper function to format timestamp for display
  const formatTimestamp = (value: string | number): string => {
    try {
      const date = new Date(value);
      if (isNaN(date.getTime())) return String(value);
      
      // Format as: YYYY-MM-DD HH:MM:SS
      return date.toISOString().replace('T', ' ').substring(0, 19);
    } catch {
      return String(value);
    }
  };

  // Helper function to check if value should be highlighted (placeholder for semantic maps)
  const isSuspicious = (value: unknown, _columnName: string): boolean => {
    // TODO: Integrate with semantic mapping rules from backend
    // For now, this is a placeholder that can be enhanced when semantic maps are loaded
    // Example: highlight known malicious file paths, suspicious registry keys, etc.
    
    if (typeof value !== 'string') return false;
    
    // Example heuristics (to be replaced with actual semantic map rules):
    // - Suspicious file paths (temp directories, startup folders)
    const suspiciousPatterns = [
      /\\temp\\/i,
      /\\appdata\\roaming\\/i,
      /\\startup\\/i,
      /powershell\.exe/i,
      /cmd\.exe/i,
      /wscript\.exe/i,
      /cscript\.exe/i
    ];
    
    return suspiciousPatterns.some(pattern => pattern.test(value));
  };

  // Helper function to handle file path clicks
  const handleFilePathClick = (path: string) => {
    // In a real implementation, this would call a bridge method to open the file location
    // For now, we'll just log it (the Python backend would handle the actual file opening)
    console.log('Open file location:', path);
    
    // TODO: Call window.bridge.open_file_location(path) when bridge method is available
    // This would be implemented in the EYE Bridge to open Windows Explorer at the file location
  };

  // Filter rows based on search text
  const filteredRows = useMemo(() => {
    if (!filterText) return rows;
    
    const lowerFilter = filterText.toLowerCase();
    return rows.filter(row => 
      Object.values(row).some(value => 
        String(value).toLowerCase().includes(lowerFilter)
      )
    );
  }, [rows, filterText]);

  // Sort rows
  const sortedRows = useMemo(() => {
    if (!sortColumn) return filteredRows;
    
    return [...filteredRows].sort((a, b) => {
      const aVal = a[sortColumn];
      const bVal = b[sortColumn];
      
      if (aVal === bVal) return 0;
      if (aVal === null || aVal === undefined) return 1;
      if (bVal === null || bVal === undefined) return -1;
      
      const comparison = aVal < bVal ? -1 : 1;
      return sortDirection === 'asc' ? comparison : -comparison;
    });
  }, [filteredRows, sortColumn, sortDirection]);

  // Paginate rows
  const paginatedRows = useMemo(() => {
    const start = (currentPage - 1) * rowsPerPage;
    return sortedRows.slice(start, start + rowsPerPage);
  }, [sortedRows, currentPage]);

  const totalPages = Math.ceil(sortedRows.length / rowsPerPage);

  const handleSort = (column: string) => {
    if (sortColumn === column) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      setSortColumn(column);
      setSortDirection('asc');
    }
  };

  const exportToCSV = () => {
    const csvContent = [
      columns.join(','),
      ...sortedRows.map(row => 
        columns.map(col => {
          const value = row[col];
          const stringValue = value === null || value === undefined ? '' : String(value);
          // Escape quotes and wrap in quotes if contains comma or quote
          return stringValue.includes(',') || stringValue.includes('"')
            ? `"${stringValue.replace(/"/g, '""')}"`
            : stringValue;
        }).join(',')
      )
    ].join('\n');

    const blob = new Blob([csvContent], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${table || 'query_results'}_${Date.now()}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const addToReport = async (row: Record<string, any>) => {
    if (!window.bridge) return;
    
    try {
      const payload = JSON.stringify({
        columns: columns,
        rows: [row],
        caption: `Evidence from ${table || 'query results'}`
      });
      
      await window.bridge.report_add_data_table(query, payload);
      console.log('Row added to report bucket');
    } catch (error) {
      console.error('Failed to add row to report:', error);
    }
  };

  const addAllToReport = async () => {
    if (!window.bridge) return;
    
    try {
      const payload = JSON.stringify({
        columns: columns,
        rows: sortedRows,
        caption: `Full result set from ${table || 'query results'}`
      });
      
      await window.bridge.report_add_data_table(query, payload);
      console.log('All rows added to report bucket');
    } catch (error) {
      console.error('Failed to add all rows to report:', error);
    }
  };

  return (
    <div className="data-viewer">
      <div className="data-viewer-header">
        <div className="query-info">
          <span className="query-label">Query:</span>
          <code className="query-text">{query}</code>
        </div>
        <div className="data-viewer-meta">
          <span className="database-info">{database} • {table}</span>
          <span className="row-count">{sortedRows.length} rows</span>
        </div>
      </div>

      <div className="data-viewer-controls">
        <input
          type="text"
          className="filter-input"
          placeholder="Filter results..."
          value={filterText}
          onChange={(e) => {
            setFilterText(e.target.value);
            setCurrentPage(1);
          }}
        />
        <button className="export-button" onClick={exportToCSV}>
          Export CSV
        </button>
        <button className="bucket-button" onClick={addAllToReport} title="Add all results to the report bucket">
          🪣 Add All to Report
        </button>
      </div>

      <div className="table-container">
        <table className="data-table">
          <thead>
            <tr>
              <th className="actions-column">Actions</th>
              {columns.map(column => (
                <th key={column} onClick={() => handleSort(column)}>
                  <div className="th-content">
                    <span>{column}</span>
                    {sortColumn === column && (
                      <span className="sort-indicator">
                        {sortDirection === 'asc' ? '↑' : '↓'}
                      </span>
                    )}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {paginatedRows.map((row, idx) => (
              <tr key={idx}>
                <td className="actions-cell">
                  <button 
                    className="row-bucket-btn" 
                    onClick={() => addToReport(row)}
                    title="Add this row to report bucket"
                  >
                    🪣
                  </button>
                </td>
                {columns.map(column => {
                  const value = row[column];
                  const isNull = value === null || value === undefined;
                  const isPath = !isNull && isFilePath(value);
                  const isTime = !isNull && isTimestamp(value, column);
                  const suspicious = !isNull && isSuspicious(value, column);
                  
                  return (
                    <td 
                      key={column}
                      className={suspicious ? 'suspicious-value' : ''}
                      title={suspicious ? 'Potentially suspicious value' : undefined}
                    >
                      {isNull ? (
                        <span className="null-value">NULL</span>
                      ) : isPath ? (
                        <span 
                          className="file-path-link" 
                          onClick={() => handleFilePathClick(String(value))}
                          title="Click to open file location"
                        >
                          {String(value)}
                        </span>
                      ) : isTime ? (
                        <span className="timestamp-value" title={`Raw: ${value}`}>
                          {formatTimestamp(value)}
                        </span>
                      ) : (
                        String(value)
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div className="pagination">
          <button 
            onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
            disabled={currentPage === 1}
          >
            Previous
          </button>
          <span className="page-info">
            Page {currentPage} of {totalPages}
          </span>
          <button 
            onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
            disabled={currentPage === totalPages}
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
};

export default DataViewer;
