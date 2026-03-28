# GUI Worker Threads Documentation

## Overview

This document describes the worker thread classes created to prevent GUI freezing in the Crow Eye forensics tool. These workers move long-running operations off the main GUI thread, keeping the interface responsive during artifact collection, data loading, and batch processing operations.

## Architecture

The worker classes follow the Qt threading model using `QThread` and `pyqtSignal` for thread-safe communication between worker threads and the main GUI thread.

### Design Pattern

```
Main GUI Thread                    Worker Thread
     │                                  │
     ├─ Create Worker                   │
     ├─ Connect Signals ────────────────┤
     ├─ Start Worker ───────────────────┤
     │                                  │
     │                              ┌───▼───┐
     │                              │  run() │
     │                              └───┬───┘
     │                                  │
     │  ◄────── Signal Emission ────────┤
     │  (progress_update)               │
     │                                  │
     │  ◄────── Signal Emission ────────┤
     │  (operation_complete)            │
     │                                  │
     └─ Handle Completion                │
```

## Worker Classes

### 1. LiveAcquisitionWorker

**Purpose**: Handles live artifact acquisition operations without blocking the GUI.

**Use Case**: When collecting artifacts from a live system (LNK files, Registry, Prefetch, Event Logs, ShimCache, AmCache, RecycleBin, SRUM, MFT, USN Journal).

**Signals**:
- `step_update(int, str)` - Emitted when a collection step updates
  - Parameters: step_index, step_message
- `log_message(str)` - Emitted when a log message should be displayed
  - Parameters: message
- `acquisition_complete(str)` - Emitted when acquisition finishes successfully
  - Parameters: success_message
- `acquisition_error(str)` - Emitted if acquisition fails
  - Parameters: error_message

**Example Usage**:

```python
from ui.gui_workers import LiveAcquisitionWorker
from PyQt5.QtCore import QEventLoop

# Define your collection function
def collect_artifacts(case_paths, windows_partition, step_callback, log_callback, cancellation_check):
    # Step 1: Collect LNK files
    step_callback(0, "Collecting LNK files...")
    log_callback("Starting LNK collection")
    # ... perform collection ...
    
    # Check for cancellation
    if cancellation_check():
        return
    
    # Step 2: Collect Registry
    step_callback(1, "Collecting Registry data...")
    # ... perform collection ...

# Create worker
worker = LiveAcquisitionWorker(
    collection_function=collect_artifacts,
    case_paths={'case_root': '/path/to/case', 'artifacts_dir': '/path/to/artifacts'},
    windows_partition='C:'
)

# Connect signals to GUI
worker.step_update.connect(lambda idx, msg: loading_dialog.update_step(idx, msg))
worker.log_message.connect(lambda msg: loading_dialog.add_log_message(msg))
worker.acquisition_complete.connect(lambda msg: show_success_message(msg))
worker.acquisition_error.connect(lambda msg: show_error_message(msg))

# Start worker (non-blocking)
worker.start()

# Use QEventLoop to wait without blocking GUI
loop = QEventLoop()
worker.finished.connect(loop.quit)
loop.exec_()

# Clean up
worker.wait()
```

**Cancellation Support**:

```python
# To cancel the operation
worker.cancel()

# The collection function should check cancellation_check() periodically
if cancellation_check():
    return  # Exit early
```

### 2. DataLoadingWorker

**Purpose**: Handles data loading operations into GUI tabs without blocking the GUI.

**Use Case**: When loading data from databases into GUI tables (logs, prefetch, registry, etc.).

**Signals**:
- `progress_update(int, int, str)` - Emitted during loading
  - Parameters: current, total, data_type
- `loading_complete(str, object)` - Emitted when loading finishes successfully
  - Parameters: data_type, loaded_data
- `loading_error(str, str)` - Emitted if loading fails
  - Parameters: data_type, error_message

**Example Usage**:

```python
from ui.gui_workers import DataLoadingWorker

# Define your loading function
def load_event_logs(progress_callback, cancellation_check, db_path):
    # Connect to database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get total count
    cursor.execute("SELECT COUNT(*) FROM event_logs")
    total = cursor.fetchone()[0]
    
    # Load data in batches
    loaded_data = []
    for i in range(0, total, 1000):
        # Check for cancellation
        if cancellation_check():
            break
        
        # Load batch
        cursor.execute("SELECT * FROM event_logs LIMIT 1000 OFFSET ?", (i,))
        batch = cursor.fetchall()
        loaded_data.extend(batch)
        
        # Report progress
        progress_callback(i + len(batch), total)
    
    conn.close()
    return loaded_data

# Create worker
worker = DataLoadingWorker(
    data_type='event_logs',
    loading_function=load_event_logs,
    db_path='/path/to/logs.db'
)

# Connect signals
worker.progress_update.connect(lambda cur, tot, dtype: update_progress_bar(cur, tot))
worker.loading_complete.connect(lambda dtype, data: populate_table(dtype, data))
worker.loading_error.connect(lambda dtype, err: show_error(dtype, err))

# Start worker
worker.start()

# Use QEventLoop to wait
loop = QEventLoop()
worker.finished.connect(loop.quit)
loop.exec_()

# Clean up
worker.wait()
```

### 3. BatchProcessingWorker

**Purpose**: Handles batch data processing operations without blocking the GUI.

**Use Case**: When processing large datasets with database queries and table population (_batch_process_data, _paginated_batch_process_data).

**Signals**:
- `batch_progress(int, int, str)` - Emitted during processing
  - Parameters: current, total, table_name
- `batch_complete(str, int)` - Emitted when processing finishes successfully
  - Parameters: table_name, loaded_count
- `batch_error(str, str)` - Emitted if processing fails
  - Parameters: table_name, error_message

**Example Usage**:

```python
from ui.gui_workers import BatchProcessingWorker

# Define your processing function
def process_batch_data(progress_callback, cancellation_check, cursor, query, batch_size):
    # Execute query
    cursor.execute(query)
    
    # Process in batches
    loaded_count = 0
    while True:
        # Check for cancellation
        if cancellation_check():
            break
        
        # Fetch batch
        batch = cursor.fetchmany(batch_size)
        if not batch:
            break
        
        # Process batch (e.g., format data, create table items)
        for row in batch:
            # ... process row ...
            loaded_count += 1
        
        # Report progress
        progress_callback(loaded_count, -1)  # -1 if total unknown
    
    return loaded_count

# Create worker
worker = BatchProcessingWorker(
    table_name='registry_data',
    processing_function=process_batch_data,
    cursor=db_cursor,
    query="SELECT * FROM registry_data",
    batch_size=500
)

# Connect signals
worker.batch_progress.connect(lambda cur, tot, tbl: update_progress(cur, tot, tbl))
worker.batch_complete.connect(lambda tbl, cnt: show_completion(tbl, cnt))
worker.batch_error.connect(lambda tbl, err: show_error(tbl, err))

# Start worker
worker.start()

# Use QEventLoop to wait
loop = QEventLoop()
worker.finished.connect(loop.quit)
loop.exec_()

# Clean up
worker.wait()
```

## Best Practices

### 1. Always Use QEventLoop Instead of QApplication.processEvents()

**Bad (Old Pattern)**:
```python
def long_operation():
    for i in range(1000):
        # Do work
        QApplication.processEvents()  # Anti-pattern!
```

**Good (New Pattern)**:
```python
def long_operation():
    worker = SomeWorker(...)
    worker.start()
    
    loop = QEventLoop()
    worker.finished.connect(loop.quit)
    loop.exec_()  # Keeps GUI responsive
    
    worker.wait()
```

### 2. Implement Cancellation Support

Always check the cancellation flag in your worker functions:

```python
def my_operation(cancellation_check, ...):
    for item in items:
        if cancellation_check():
            return  # Exit early
        
        # Process item
```

### 3. Report Progress Regularly

Emit progress updates to keep the user informed:

```python
def my_operation(progress_callback, ...):
    total = len(items)
    for i, item in enumerate(items):
        # Process item
        progress_callback(i + 1, total)
```

### 4. Handle Errors Gracefully

Catch exceptions and emit error signals:

```python
def run(self):
    try:
        result = self.operation_function(...)
        self.operation_complete.emit(result)
    except Exception as e:
        self.operation_error.emit(str(e))
```

### 5. Clean Up Resources

Always wait for worker threads to finish:

```python
worker.start()
# ... wait for completion ...
worker.wait()  # Ensure thread is fully finished
```

## Migration Guide

### Migrating from QApplication.processEvents()

**Before**:
```python
def parse_all_live_artifacts(self):
    dialog = LoadingDialog("CROW EYE SYSTEM", self.main_window)
    dialog.show()
    
    # Step 1
    dialog.update_step(0, "Collecting LNK files...")
    QApplication.processEvents()  # Blocks GUI
    collect_lnk_files()
    
    # Step 2
    dialog.update_step(1, "Collecting Registry...")
    QApplication.processEvents()  # Blocks GUI
    collect_registry()
    
    dialog.close()
```

**After**:
```python
def parse_all_live_artifacts(self):
    dialog = LoadingDialog("CROW EYE SYSTEM", self.main_window)
    dialog.show()
    
    # Create worker
    worker = LiveAcquisitionWorker(
        collection_function=self._collect_all_artifacts,
        case_paths=self.case_paths,
        windows_partition=self.get_windows_partition()
    )
    
    # Connect signals
    worker.step_update.connect(lambda idx, msg: dialog.update_step(idx, msg))
    worker.acquisition_complete.connect(lambda msg: dialog.show_completion(msg))
    
    # Start worker (non-blocking)
    worker.start()
    
    # Wait without blocking GUI
    loop = QEventLoop()
    worker.finished.connect(loop.quit)
    loop.exec_()
    
    worker.wait()
    dialog.close()

def _collect_all_artifacts(self, case_paths, windows_partition, step_callback, log_callback, cancellation_check):
    # Step 1
    step_callback(0, "Collecting LNK files...")
    log_callback("Starting LNK collection")
    collect_lnk_files()
    
    if cancellation_check():
        return
    
    # Step 2
    step_callback(1, "Collecting Registry...")
    log_callback("Starting Registry collection")
    collect_registry()
```

## Testing

Run the worker structure tests:

```bash
python dev/test_gui_workers.py
```

Expected output:
```
============================================================
GUI Worker Thread Structure Tests
============================================================

=== Testing LiveAcquisitionWorker Structure ===
✓ LiveAcquisitionWorker structure is correct
  - Signals: step_update, log_message, acquisition_complete, acquisition_error
  - Methods: cancel, is_cancelled, run
  - Cancellation support: Working

=== Testing DataLoadingWorker Structure ===
✓ DataLoadingWorker structure is correct
  - Signals: progress_update, loading_complete, loading_error
  - Methods: cancel, is_cancelled, run
  - Cancellation support: Working

=== Testing BatchProcessingWorker Structure ===
✓ BatchProcessingWorker structure is correct
  - Signals: batch_progress, batch_complete, batch_error
  - Methods: cancel, is_cancelled, run
  - Cancellation support: Working

=== Testing Worker Signal Definitions ===
✓ All worker signals are properly defined as pyqtSignal
  - LiveAcquisitionWorker: 4 signals
  - DataLoadingWorker: 3 signals
  - BatchProcessingWorker: 3 signals

============================================================
✓ All worker structure tests passed!
============================================================
```

## Troubleshooting

### Worker Thread Not Starting

**Problem**: Worker thread doesn't seem to start or signals aren't emitted.

**Solution**: Ensure you're using QEventLoop to wait for completion:

```python
worker.start()
loop = QEventLoop()
worker.finished.connect(loop.quit)
loop.exec_()  # This keeps the event loop running
worker.wait()
```

### GUI Still Freezing

**Problem**: GUI still freezes even with worker threads.

**Solution**: Check that you're not calling blocking operations on the main thread. All long-running operations should be in the worker's `run()` method.

### Signals Not Received

**Problem**: Signals emitted from worker thread aren't received in main thread.

**Solution**: Qt automatically handles cross-thread signal delivery. Ensure:
1. Signals are defined as class attributes (not instance attributes)
2. You're using `pyqtSignal` from `PyQt5.QtCore`
3. The worker thread is still running when signals are emitted

### Memory Leaks

**Problem**: Worker threads accumulate in memory.

**Solution**: Always call `worker.wait()` after the thread finishes to ensure proper cleanup:

```python
worker.start()
# ... wait for completion ...
worker.wait()  # Clean up thread resources
```

## References

- [Qt Threading Documentation](https://doc.qt.io/qt-5/thread-basics.html)
- [PyQt5 QThread Documentation](https://www.riverbankcomputing.com/static/Docs/PyQt5/api/qtcore/qthread.html)
- [Crow Eye GUI Freezing Bugfix Spec](.kiro/specs/gui-freezing-and-ux-issues-fix/)
