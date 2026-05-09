# EYE Tab Context Settings Integration Pattern

## Overview

This document describes the integration pattern for the Context Window Settings Dialog within the EYE Tab. This pattern is demonstrated in the stub implementation (`eye_tab_stub.py`) and will be used when implementing the full EYE Tab in Task 17.


## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         EYE Tab                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │                    Chat Toolbar                         │ │
│  │  [⚙️ Context Settings] [🗑️ Clear] [📥 Export]          │ │
│  └────────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────────┐ │
│  │                                                         │ │
│  │              Chat Interface (React SPA)                │ │
│  │                                                         │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                            │
                            │ Click "Context Settings"
                            ▼
┌─────────────────────────────────────────────────────────────┐
│           ContextWindowSettingsDialog                        │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  Backend Selection | Token Budget | History Mgmt       │ │
│  │                                                         │ │
│  │  Max Total Tokens: [8000]                              │ │
│  │  System Prompt:    [2000]                              │ │
│  │  RAG Context:      [2000]                              │ │
│  │  History:          [4000]                              │ │
│  │                                                         │ │
│  │              [Reset] [Cancel] [Save]                   │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                            │
                            │ Save
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              ContextWindowConfigManager                      │
│  • Validates configuration                                   │
│  • Saves to configs/eye_config.json                         │
│  • Returns updated config                                    │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                   ContextManager                             │
│  • update_context_config(new_config)                        │
│  • Updates runtime values:                                   │
│    - max_total_tokens                                        │
│    - token_budget                                            │
│    - history_config                                          │
│  • Applies changes immediately                               │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                   Success Message                            │
│  "Configuration Updated"                                     │
│  Max Total Tokens: 8,000                                     │
│  Conversation History Budget: 4,000                          │
│  Sliding Window Size: 10                                     │
│  Changes are now active.                                     │
└─────────────────────────────────────────────────────────────┘
```

## Integration Steps

### Step 1: Add Context Settings Button to Toolbar

```python
def _create_toolbar(self) -> QToolBar:
    """Create chat toolbar with Context Settings button."""
    toolbar = QToolBar("Chat Toolbar")
    
    # Add Context Settings button
    context_settings_button = QPushButton("⚙️ Context Settings")
    context_settings_button.setToolTip("Configure context window and token budget settings")
    context_settings_button.clicked.connect(self._on_context_settings_clicked)
    toolbar.addWidget(context_settings_button)
    
    return toolbar
```

### Step 2: Implement Click Handler

```python
def _on_context_settings_clicked(self):
    """
    Handle Context Settings button click.
    
    Integration pattern:
    1. Get current backend from context manager
    2. Open ContextWindowSettingsDialog
    3. If dialog accepted (saved), get new configuration
    4. Call ContextManager.update_context_config() to apply changes
    5. Display success message
    """
    # Get current backend
    current_backend = self.context_manager.model_router.config.get("backend", "ollama")
    
    # Open settings dialog
    dialog = ContextWindowSettingsDialog(
        config_manager=self.config_manager,
        current_backend=current_backend,
        parent=self
    )
    
    # Execute dialog
    result = dialog.exec_()
    
    if result == ContextWindowSettingsDialog.Accepted:
        # Dialog was saved, apply configuration
        self._apply_new_configuration(current_backend)
```

### Step 3: Apply Configuration to ContextManager

```python
def _apply_new_configuration(self, backend: str):
    """Apply new configuration after dialog save."""
    try:
        # Get updated configuration from config manager
        new_config = self.config_manager.get_config_for_backend(backend)
        
        # Apply configuration to context manager
        self.context_manager.update_context_config(new_config)
        
        # Display success message
        self._show_success_message(new_config)
        
    except Exception as e:
        # Display error message
        self._show_error_message(str(e))
```

### Step 4: Display Success Message

```python
def _show_success_message(self, config: dict):
    """Display success message with configuration details."""
    QMessageBox.information(
        self,
        "Configuration Updated",
        "Context window configuration has been updated successfully.\n\n"
        f"Max Total Tokens: {config['max_total_tokens']:,}\n"
        f"Conversation History Budget: {config['token_budget']['conversation_history']:,}\n"
        f"Sliding Window Size: {config['history_management']['sliding_window_size']}\n\n"
        "Changes are now active."
    )
```

## Key Components

### ContextManager.update_context_config()

The `update_context_config()` method in ContextManager applies new configuration at runtime:

```python
def update_context_config(self, new_config: Dict[str, Any]):
    """
    Update context window configuration at runtime.
    
    Args:
        new_config: New configuration dict with max_total_tokens, token_budget, etc.
    """
    # Validate and save configuration
    self.config_manager.save_config(new_config)
    
    # Update runtime values
    self.max_total_tokens = new_config.get("max_total_tokens", self.max_total_tokens)
    self.token_budget = new_config.get("token_budget", self.token_budget)
    self.history_config = new_config.get("history_management", self.history_config)
    self.config = new_config
    
    self.logger.info(f"Context configuration updated: {self.max_total_tokens} total tokens")
```

**Key Features**:
- Validates configuration before applying
- Updates runtime values immediately
- No restart required
- Logs configuration changes

### ContextWindowConfigManager

Manages configuration loading, validation, and persistence:

```python
class ContextWindowConfigManager:
    """Manages context window configuration."""
    
    def get_config_for_backend(self, backend: str) -> Dict[str, Any]:
        """Get configuration for specific backend."""
        
    def save_config(self, config: Dict[str, Any]):
        """Save configuration to disk."""
        
    def apply_preset(self, backend: str) -> Dict[str, Any]:
        """Apply preset configuration for backend."""
```

### ContextWindowSettingsDialog

Provides UI for editing configuration:

```python
class ContextWindowSettingsDialog(QDialog):
    """Settings dialog for context window configuration."""
    
    def __init__(self, config_manager, current_backend, parent=None):
        """Initialize with config manager and current backend."""
        
    def _on_save(self):
        """Save configuration and close dialog."""
        # Validate configuration
        # Save using config manager
        # Accept dialog (returns Accepted)
```

## Configuration Flow

1. **User Action**: User clicks "Context Settings" button in toolbar
2. **Dialog Opens**: ContextWindowSettingsDialog opens with current configuration
3. **User Edits**: User modifies token budgets, window size, etc.
4. **Validation**: Dialog validates configuration before allowing save
5. **Save**: Dialog saves to `configs/eye_config.json` via ContextWindowConfigManager
6. **Apply**: EYE Tab calls `ContextManager.update_context_config(new_config)`
7. **Runtime Update**: ContextManager updates runtime values immediately
8. **Feedback**: Success message displays new configuration details

## Error Handling

### Configuration Validation Errors

```python
try:
    self.context_manager.update_context_config(new_config)
except ValueError as e:
    QMessageBox.warning(
        self,
        "Validation Error",
        f"Configuration validation failed:\n\n{str(e)}"
    )
```

### Save Errors

```python
try:
    self.config_manager.save_config(config)
except Exception as e:
    QMessageBox.critical(
        self,
        "Save Error",
        f"Failed to save configuration:\n\n{str(e)}"
    )
```

## Testing

Integration tests verify:

1. **Dialog Opening**: Context Settings button opens dialog
2. **Configuration Application**: Saved settings are applied to ContextManager
3. **Success Message**: Success message displays after save
4. **Error Handling**: Errors are handled gracefully
5. **Cancel Behavior**: Cancelling dialog doesn't apply changes

See `test_eye_tab_integration.py` for complete test suite.

## Future Implementation (Task 17)

When implementing the full EYE Tab, integrate this pattern:

### React Frontend Integration

```typescript
// ChatInterface.tsx
const ChatInterface: React.FC = () => {
  const handleContextSettings = () => {
    // Call Python backend via QWebChannel
    window.bridge.open_context_settings();
  };
  
  return (
    <div className="chat-toolbar">
      <button onClick={handleContextSettings}>
        ⚙️ Context Settings
      </button>
    </div>
  );
};
```

### QWebChannel Bridge

```python
class EYEBridge(QObject):
    """QWebChannel bridge for React-Python communication."""
    
    @pyqtSlot()
    def open_context_settings(self):
        """Open Context Settings Dialog from React."""
        # Trigger the same flow as toolbar button
        self.eye_tab._on_context_settings_clicked()
```

### Real-time Context Stats Display

```typescript
// ContextStatsDisplay.tsx
const ContextStatsDisplay: React.FC = () => {
  const [stats, setStats] = useState(null);
  
  useEffect(() => {
    // Poll context stats from backend
    const interval = setInterval(async () => {
      const result = await window.bridge.get_context_stats();
      setStats(JSON.parse(result));
    }, 5000);
    
    return () => clearInterval(interval);
  }, []);
  
  return (
    <div className="context-stats">
      <span>Tokens: {stats?.total_tokens} / {stats?.max_total_tokens}</span>
      <span>Messages: {stats?.total_messages}</span>
    </div>
  );
};
```

## Configuration Files

### configs/eye_config.json

```json
{
  "integration_type": "local_cli",
  "backend": "ollama",
  "model_name": "llama2",
  "context_window": {
    "max_total_tokens": 8000,
    "token_budget": {
      "system_prompt": 2000,
      "rag_context": 2000,
      "conversation_history": 4000,
      "tool_definitions": 1000,
      "response_buffer": 1000
    },
    "history_management": {
      "sliding_window_size": 10,
      "preserve_first_message": true,
      "preserve_tool_messages": true,
      "truncation_strategy": "sliding_window"
    }
  }
}
```

### configs/context_window_presets.json

Contains preset configurations for all supported backends (GPT-4, Claude, Ollama, etc.)

## Best Practices

1. **Always validate configuration** before applying to ContextManager
2. **Display clear success messages** with configuration details
3. **Handle errors gracefully** with user-friendly messages
4. **Log configuration changes** for audit trail
5. **Test integration thoroughly** with unit and integration tests
6. **Provide tooltips** on settings for user guidance
7. **Show current values** when opening dialog
8. **Allow preset restoration** for easy reset

## Summary

This integration pattern provides:

- ✅ Clean separation of concerns (UI, Config, Runtime)
- ✅ Immediate configuration updates (no restart required)
- ✅ User-friendly success/error messages
- ✅ Comprehensive validation
- ✅ Audit logging
- ✅ Easy testing
- ✅ Extensible for future features

The stub implementation demonstrates this pattern and can be used as a reference when implementing the full EYE Tab in Task 17.
