# QWebChannel Bridge Integration

## Overview

This document describes the QWebChannel integration that enables communication between the React frontend and Python backend in the EYE Forensic Assistant.


## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    React Frontend                            │
│  ┌──────────────┐         ┌──────────────┐                 │
│  │ ChatInterface│────────▶│  bridge.ts   │                 │
│  └──────────────┘         └──────┬───────┘                 │
│                                   │                          │
└───────────────────────────────────┼──────────────────────────┘
                                    │
                          QWebChannel (qwebchannel.js)
                                    │
┌───────────────────────────────────┼──────────────────────────┐
│                    Python Backend │                          │
│                          ┌────────▼────────┐                │
│                          │   EYEBridge     │                │
│                          │  (@pyqtSlot)    │                │
│                          └────────┬────────┘                │
│                                   │                          │
│                          ┌────────▼────────┐                │
│                          │ Context Manager │                │
│                          └─────────────────┘                │
└─────────────────────────────────────────────────────────────┘
```

## Components

### 1. index.html

Added QWebChannel script tag to load the PyQt5 bridge library:

```html
<script type="text/javascript" src="qrc:///qtwebchannel/qwebchannel.js"></script>
```

This script is provided by PyQt5 and must be loaded before the React application initializes.

### 2. bridge.ts

Core bridge integration module that provides:

#### Initialization
- `initializeBridge()`: Establishes QWebChannel connection
- Returns a Promise that resolves to the EYEBridge interface
- Handles standalone mode gracefully for development

#### Communication
- `sendMessage(query)`: Convenience wrapper for `window.bridge.process_query()`
- Handles errors and bridge availability checks

#### Signal Listeners
- `onQueryComplete(callback)`: Register listener for async query completion
- `onReportUpdated(callback)`: Register listener for report state changes
- `onErrorOccurred(callback)`: Register listener for backend errors

#### Utility Functions
- `isBridgeReady()`: Check if bridge is initialized
- `getBridge()`: Get the bridge instance

### 3. ChatInterface.tsx

Updated to use the bridge module:

#### Initialization (useEffect)
```typescript
useEffect(() => {
  const setupBridge = async () => {
    await initializeBridge();
    setBridgeReady(true);
    
    // Set up signal listeners
    onQueryComplete((responseJson) => { /* handle */ });
    onReportUpdated((reportJson) => { /* handle */ });
    onErrorOccurred((errorMessage) => { /* handle */ });
  };
  
  setupBridge();
}, []);
```

#### Sending Messages
```typescript
const sendMessage = async (query: string) => {
  if (isBridgeReady()) {
    const responseJson = await bridgeSendMessage(query);
    const response = JSON.parse(responseJson);
    // Handle response
  }
};
```

## Signal Flow

### Synchronous Request-Response
1. User types query in ChatInterface
2. `sendMessage()` calls `bridgeSendMessage(query)`
3. Bridge calls `window.bridge.process_query(query)`
4. Python backend processes query
5. Returns JSON response string
6. React parses and displays response

### Asynchronous Signals
1. Python backend emits signal (e.g., `query_complete.emit(json_data)`)
2. QWebChannel forwards signal to JavaScript
3. Registered callbacks in `bridge.ts` are invoked
4. React components update state based on signal data

## Python Backend Interface

The Python backend must implement the following @pyqtSlot methods:

```python
class EYEBridge(QObject):
    # Signals
    query_complete = pyqtSignal(str)
    report_updated = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    
    @pyqtSlot(str, result=str)
    def process_query(self, user_query: str) -> str:
        """Process natural language query."""
        pass
    
    @pyqtSlot(str, str, result=str)
    def query_database(self, database_name: str, sql_query: str) -> str:
        """Execute SQL query."""
        pass
    
    # ... other methods from types.ts EYEBridge interface
```

## Development Mode

The bridge gracefully handles standalone mode when QWebChannel is not available:

- `initializeBridge()` rejects with error
- `isBridgeReady()` returns false
- ChatInterface displays mock responses
- Allows UI development without Python backend

## Testing

### Manual Testing Checklist

1. **Bridge Initialization**
   - [ ] Bridge initializes successfully in PyQt5 QWebEngineView
   - [ ] Console logs "QWebChannel bridge initialized successfully"
   - [ ] Status indicator shows "Connected"

2. **Message Sending**
   - [ ] User can send queries through input bar
   - [ ] Queries reach Python backend via `process_query()`
   - [ ] Responses are displayed in chat

3. **Signal Listeners**
   - [ ] `query_complete` signal triggers callback
   - [ ] `report_updated` signal triggers callback
   - [ ] `error_occurred` signal displays error message

4. **Error Handling**
   - [ ] Bridge errors are caught and logged
   - [ ] User sees friendly error messages
   - [ ] Application continues to function after errors

5. **Standalone Mode**
   - [ ] UI renders correctly without bridge
   - [ ] Mock responses work in development
   - [ ] Status indicator shows "Standalone Mode"

### Integration Testing

To test the bridge integration:

1. Build the React app: `npm run build`
2. Run the Python application with QWebEngineView
3. Load the built React app in QWebEngineView
4. Verify bridge initialization in browser console
5. Send test queries and verify responses

## Troubleshooting

### Bridge Not Initializing

**Symptom**: Console shows "QWebChannel transport not available"

**Solutions**:
- Ensure QWebEngineView is properly configured
- Verify qwebchannel.js is loaded before React app
- Check that EYEBridge is registered with QWebChannel in Python

### Signals Not Firing

**Symptom**: Signal callbacks never execute

**Solutions**:
- Verify signal connections in `connectSignalListeners()`
- Check that Python backend emits signals correctly
- Ensure signal names match between Python and TypeScript

### Type Errors

**Symptom**: TypeScript compilation errors

**Solutions**:
- Verify `types.ts` EYEBridge interface matches Python implementation
- Check that all @pyqtSlot methods return strings
- Ensure JSON serialization/deserialization is correct

## Future Enhancements

1. **Reconnection Logic**: Auto-reconnect if bridge connection drops
2. **Request Queuing**: Queue requests if bridge is temporarily unavailable
3. **Typed Responses**: Use TypeScript generics for type-safe responses
4. **Performance Monitoring**: Track bridge call latency and errors
5. **Unit Tests**: Add Jest tests for bridge module functions
