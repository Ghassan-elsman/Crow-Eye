# EYE AI Chat Interface - React Components

This directory contains the React frontend components for the EYE (Enhanced Yield Engine) AI Forensic Assistant chat interface.

## Components Overview

### ChatInterface.tsx
Main container component that orchestrates the entire chat experience.

**Features:**
- Manages conversation state and message history
- Handles QWebChannel bridge connection detection
- Processes user queries through Python backend
- Displays loading states during query processing
- Supports standalone development mode when bridge is unavailable

**Props:** None (root component)

### MessageList.tsx
Scrollable list component that displays conversation history.

**Features:**
- Renders user and assistant messages with distinct styling
- Auto-scrolls to bottom when new messages arrive
- Displays markdown-formatted content using react-markdown
- Embeds DataViewer components for query results
- Shows ActionChips for suggested follow-up actions

**Props:**
- `messages: Message[]` - Array of conversation messages
- `onActionChipClick: (query: string) => void` - Callback when action chip is clicked

### InputBar.tsx
Text input component with send button and keyboard shortcuts.

**Features:**
- Multi-line textarea with auto-resize
- Send on Enter, new line on Shift+Enter
- Disabled state during query processing
- Controlled/uncontrolled input support
- Dark theme styling

**Props:**
- `onSend: (message: string) => void` - Callback when message is sent
- `disabled?: boolean` - Disable input during processing
- `value?: string` - Controlled input value
- `onChange?: (value: string) => void` - Controlled input change handler

### DataViewer.tsx
Interactive table component for displaying database query results.

**Features:**
- Sortable columns (click header to sort)
- Client-side filtering with search box
- Pagination (50 rows per page)
- CSV export functionality
- Displays query metadata (database, table, row count)
- Handles NULL values with special styling
- Dark theme with scrollable table

**Props:**
- `columns: string[]` - Column names
- `rows: Record<string, any>[]` - Data rows
- `query: string` - SQL query that generated results
- `database: string` - Source database name
- `table: string` - Source table name

### ActionChips.tsx
Clickable suggestion chips for follow-up actions.

**Features:**
- Displays suggested next actions from AI
- Hover effects and animations
- Optional icon support
- Populates input field when clicked

**Props:**
- `chips: ActionChip[]` - Array of action suggestions
- `onChipClick: (query: string) => void` - Callback when chip is clicked

## TypeScript Interfaces

### Message
```typescript
interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  data_viewer?: DataViewerProps;
  action_chips?: ActionChip[];
}
```

### ActionChip
```typescript
interface ActionChip {
  id: string;
  label: string;
  query: string;
  icon?: string;
}
```

### DataViewerProps
```typescript
interface DataViewerProps {
  columns: string[];
  rows: Record<string, any>[];
  query: string;
  database: string;
  table: string;
}
```

### EYEBridge (QWebChannel)
```typescript
interface EYEBridge {
  process_query: (query: string) => Promise<string>;
  query_database: (database: string, sql: string) => Promise<string>;
  search_artifacts: (searchConfig: string) => Promise<string>;
  get_schema: (database: string, table: string) => Promise<string>;
  propose_semantic_mapping: (ruleJson: string) => Promise<string>;
  // ... additional methods for report building
}
```

## Styling

All components use a consistent dark theme matching the PyQt5 UI:

**Color Palette:**
- Background: `#16171d`
- Surface: `#1a1c24`
- Border: `#2e303a`
- Text: `#e5e7eb`
- Text Secondary: `#9ca3af`
- Accent: `#c084fc` (purple)
- Code Background: `#1f2028`

**Typography:**
- Sans-serif: System fonts (-apple-system, BlinkMacSystemFont, Segoe UI, Roboto)
- Monospace: Consolas, Monaco, Courier New

## QWebChannel Integration

The components communicate with the Python backend via QWebChannel bridge:

```typescript
// Bridge is available at window.bridge
const response = await window.bridge.process_query(userQuery);
const data = JSON.parse(response);
```

**Bridge Response Format:**
```json
{
  "response": "AI response text",
  "data_viewer": {
    "columns": ["col1", "col2"],
    "rows": [{"col1": "val1", "col2": "val2"}],
    "query": "SELECT * FROM table",
    "database": "registry_data.db",
    "table": "registry_keys"
  },
  "action_chips": [
    {"id": "1", "label": "Show Timeline", "query": "Show timeline"}
  ],
  "error": null
}
```

## Development

**Run development server:**
```bash
npm run dev
```

**Build for production:**
```bash
npm run build
```

**Lint code:**
```bash
npm run lint
```

## Integration with PyQt5

The React app is rendered inside a PyQt5 QWebEngineView widget. The QWebChannel bridge enables bidirectional communication between JavaScript and Python.

**Python side (Task 14.2):**
```python
from PyQt5.QtWebChannel import QWebChannel
from eye.ui.eye_bridge import EYEBridge

# Create bridge and expose to JavaScript
bridge = EYEBridge(context_manager)
channel = QWebChannel()
channel.registerObject('bridge', bridge)
web_view.page().setWebChannel(channel)
```

## Notes

- Components use React hooks (functional components only)
- All styling is in separate CSS files for maintainability
- TypeScript strict mode enabled for type safety
- Markdown rendering via react-markdown library
- No external UI frameworks (custom components only)
- Designed for embedded use in PyQt5 application
