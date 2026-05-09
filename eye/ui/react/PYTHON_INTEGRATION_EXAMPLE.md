# Python Backend Integration Example

This document provides an example of how to integrate the React frontend with the Python backend using QWebChannel.

## Python Backend Implementation

```python
from PyQt5.QtCore import QObject, pyqtSlot, pyqtSignal
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtWebChannel import QWebChannel
import json

class EYEBridge(QObject):
    """
    QWebChannel bridge for React-Python communication.
    
    This class exposes Python methods to the React frontend and emits
    signals for async updates.
    """
    
    # Signals for async operations
    query_complete = pyqtSignal(str)  # JSON response
    report_updated = pyqtSignal(str)  # Updated report JSON
    error_occurred = pyqtSignal(str)  # Error message
    
    def __init__(self, context_manager, parent=None):
        super().__init__(parent)
        self.context_manager = context_manager
        
    @pyqtSlot(str, result=str)
    def process_query(self, user_query: str) -> str:
        """
        Process natural language query through Context Manager.
        
        Args:
            user_query: User's natural language question
            
        Returns:
            JSON string: {
                "response": "AI response text",
                "data_viewer": {...} | null,
                "action_chips": [...],
                "error": null | "error message"
            }
        """
        try:
            result = self.context_manager.process_query(user_query)
            return json.dumps(result)
        except Exception as e:
            return json.dumps({"error": str(e)})
    
    @pyqtSlot(str, str, result=str)
    def query_database(self, database_name: str, sql_query: str) -> str:
        """Execute SQL query against forensic database."""
        try:
            # Implementation here
            return json.dumps({"columns": [], "rows": [], "row_count": 0})
        except Exception as e:
            return json.dumps({"error": str(e)})
    
    @pyqtSlot(str, result=str)
    def search_artifacts(self, search_config_json: str) -> str:
        """Search across forensic databases."""
        try:
            # Implementation here
            return json.dumps({"results": [], "total_matches": 0})
        except Exception as e:
            return json.dumps({"error": str(e)})
    
    @pyqtSlot(str, str, result=str)
    def get_schema(self, database_name: str, table_name: str) -> str:
        """Get table schema information."""
        try:
            # Implementation here
            return json.dumps({"columns": [], "sample_rows": [], "row_count": 0})
        except Exception as e:
            return json.dumps({"error": str(e)})
    
    @pyqtSlot(str, result=str)
    def propose_semantic_mapping(self, rule_json: str) -> str:
        """Propose new semantic mapping rule (triggers HitL dialog)."""
        try:
            # Implementation here
            return json.dumps({"approved": False, "modified_rule": None})
        except Exception as e:
            return json.dumps({"error": str(e)})
    
    @pyqtSlot(result=str)
    def get_report_state(self) -> str:
        """Get current report JSON state."""
        try:
            # Implementation here
            return json.dumps({"blocks": []})
        except Exception as e:
            return json.dumps({"error": str(e)})
    
    @pyqtSlot(str, str, result=str)
    def report_append_section(self, title: str, markdown_content: str) -> str:
        """Add new text block to report."""
        try:
            # Implementation here
            return json.dumps({"success": True, "block_id": "block-123"})
        except Exception as e:
            return json.dumps({"error": str(e)})
    
    @pyqtSlot(str, str, result=str)
    def report_add_data_table(self, sql_query: str, columns_json: str) -> str:
        """Add interactive table block to report."""
        try:
            # Implementation here
            return json.dumps({"success": True, "block_id": "block-124"})
        except Exception as e:
            return json.dumps({"error": str(e)})
    
    @pyqtSlot(str, str, result=str)
    def report_add_image(self, image_path: str, caption: str) -> str:
        """Add image block to report."""
        try:
            # Implementation here
            return json.dumps({"success": True, "block_id": "block-125"})
        except Exception as e:
            return json.dumps({"error": str(e)})
    
    @pyqtSlot(str, str, result=str)
    def report_edit_section(self, block_id: str, new_content: str) -> str:
        """Edit existing report block."""
        try:
            # Implementation here
            return json.dumps({"success": True})
        except Exception as e:
            return json.dumps({"error": str(e)})
    
    @pyqtSlot(str, result=str)
    def report_delete_section(self, block_id: str) -> str:
        """Delete report block."""
        try:
            # Implementation here
            return json.dumps({"success": True})
        except Exception as e:
            return json.dumps({"error": str(e)})
    
    @pyqtSlot(str, result=str)
    def export_report(self, format_type: str) -> str:
        """Export report (triggers HitL approval dialog)."""
        try:
            # Implementation here
            return json.dumps({"success": True, "file_path": "/path/to/report.pdf"})
        except Exception as e:
            return json.dumps({"error": str(e)})


class EYETab(QWidget):
    """EYE Assistant tab in the main Crow-eye application."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
        
    def setup_ui(self):
        """Initialize the UI with QWebEngineView and QWebChannel."""
        layout = QVBoxLayout(self)
        
        # Create QWebEngineView for React app
        self.web_view = QWebEngineView()
        
        # Create QWebChannel
        self.channel = QWebChannel()
        
        # Create and register bridge
        self.bridge = EYEBridge(context_manager=None)  # Pass actual context manager
        self.channel.registerObject('bridge', self.bridge)
        
        # Set channel on web page
        self.web_view.page().setWebChannel(self.channel)
        
        # Load React app (built version)
        react_app_path = os.path.join(os.path.dirname(__file__), 'react', 'dist', 'index.html')
        self.web_view.setUrl(QUrl.fromLocalFile(react_app_path))
        
        layout.addWidget(self.web_view)
        
    def emit_query_complete(self, response_data: dict):
        """Emit query_complete signal with response data."""
        self.bridge.query_complete.emit(json.dumps(response_data))
        
    def emit_report_updated(self, report_data: dict):
        """Emit report_updated signal with report data."""
        self.bridge.report_updated.emit(json.dumps(report_data))
        
    def emit_error(self, error_message: str):
        """Emit error_occurred signal."""
        self.bridge.error_occurred.emit(error_message)
```

## Integration Steps

1. **Build React App**
   ```bash
   cd eye/ui/react
   npm run build
   ```

2. **Create EYEBridge Class**
   - Implement all @pyqtSlot methods from the example above
   - Ensure all methods return JSON strings
   - Connect to your Context Manager and other services

3. **Set Up QWebChannel**
   - Create QWebChannel instance
   - Register EYEBridge with name 'bridge'
   - Set channel on QWebEngineView page

4. **Load React App**
   - Load the built index.html from dist/ directory
   - Use QUrl.fromLocalFile() for local file loading

5. **Test Integration**
   - Open browser console in QWebEngineView
   - Check for "QWebChannel bridge initialized successfully"
   - Send test queries and verify responses

## Signal Usage Example

```python
# In your Context Manager or async processing code
def process_query_async(self, query: str):
    """Process query asynchronously and emit signal when complete."""
    try:
        result = self.llm.generate(query)
        response_data = {
            "response": result.text,
            "data_viewer": None,
            "action_chips": [],
            "error": None
        }
        # Emit signal to notify React frontend
        self.bridge.query_complete.emit(json.dumps(response_data))
    except Exception as e:
        self.bridge.error_occurred.emit(str(e))
```

## Debugging Tips

1. **Enable Web Inspector**
   ```python
   from PyQt5.QtWebEngineWidgets import QWebEngineSettings
   
   settings = self.web_view.settings()
   settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
   settings.setAttribute(QWebEngineSettings.ErrorPageEnabled, True)
   ```

2. **Check Console Logs**
   - Right-click in QWebEngineView → Inspect
   - Check Console tab for JavaScript errors
   - Look for "QWebChannel bridge initialized successfully"

3. **Verify Bridge Registration**
   ```python
   print(f"Bridge registered: {self.channel.registeredObjects()}")
   ```

4. **Test Bridge Methods**
   ```python
   # Test from Python side
   result = self.bridge.process_query("test query")
   print(f"Result: {result}")
   ```
