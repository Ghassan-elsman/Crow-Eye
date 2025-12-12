"""
Row Detail Dialog Handler - Crow Eye
===================================

This module provides functionality to handle double-click events on table rows
and display detailed information in a dialog.

Author: Ghassan Elsman
"""

from PyQt5 import QtWidgets
from ui.row_detail_dialog import RowDetailDialog

# Mapping of table widget names to proper descriptive names
TABLE_NAME_MAPPING = {
    "tableWidget_2": "System Services",
    "tableWidget_3": "USB Devices",
    "tableWidget_4": "USB Instance",
    "tableWidget_5": "USB Properties",
    "tableWidget_6": "USB Devices",
    "tableWidget_7": "USB Volume",
    "ShimCache_table": "ShimCache",
    "ShimCache_main_table": "ShimCache",
    "MachineRun_table": "Machine Run",
    "MachineRunOnce_tabel": "Machine Run Once",
    "UserRun_table": "User Run",
    "UserRunOnce_table": "User Run Once",
    "LastUpdate_table": "Last Update",
    "LastUpdateInfo_table": "Last Update Info",
    "ShutDown_table": "Shutdown Info",
    "Browser_history_table": "Browser History",
    "NetworkLists_table": "Network Lists",
    # Add more mappings as needed
}

def handle_table_double_click(main_window, item):
    """Handle double-click event on table rows to show detailed information
    
    Args:
        main_window: The main application window
        item: The table item that was double-clicked
    """
    try:
        # Get the table widget that was clicked
        table = item.tableWidget()
        if not table:
            return
            
        # Get the row data
        row = item.row()
        column_count = table.columnCount()
        headers = []
        data = {}
        
        # Extract headers and data
        for col in range(column_count):
            header_item = table.horizontalHeaderItem(col)
            if header_item:
                header = header_item.text()
                headers.append(header)
                cell_item = table.item(row, col)
                data[header] = cell_item.text() if cell_item else ""
        
        # Get table name for the dialog title
        table_object_name = table.objectName()
        # Use the mapping if available, otherwise try to format the object name
        if table_object_name in TABLE_NAME_MAPPING:
            table_name = TABLE_NAME_MAPPING[table_object_name]
        elif table_object_name:
            # Try to make a friendly name from the object name
            # Remove common suffixes
            name = table_object_name.replace("_table", "").replace("tableWidget_", "")
            # Replace underscores with spaces and title case
            table_name = name.replace("_", " ").title()
        else:
            table_name = "Forensic Data"
            
        # Determine Row Name (heuristic)
        row_name = "Unknown Row"
        # Priority keys to look for
        name_keys = ["Name", "Filename", "Executable Name", "Process Name", "Service Name", "Device Name", "User", "Key"]
        
        # Try to find a matching key
        for key in name_keys:
            if key in data and data[key]:
                row_name = data[key]
                break
        
        # Fallback: use the first available value if no priority key found
        if row_name == "Unknown Row" and data:
            # Get the first value from the data dictionary
            first_value = next(iter(data.values()))
            if first_value:
                row_name = first_value
                
        # Get Row Number (1-based)
        row_number = row + 1
        
        # Create and show the detail dialog
        dialog = RowDetailDialog(data, table_name, row_name, row_number, main_window)
        dialog.show()
        
    except Exception as e:
        print(f"[Error] Failed to show row detail dialog: {str(e)}")
        import traceback
        traceback.print_exc()

def connect_table_double_click_events(ui_instance):
    """Connect double-click events to all table widgets in the application
    
    Args:
        ui_instance: The UI instance containing the table widgets
    """
    try:
        # Find all table widgets in the application
        table_widgets = find_all_table_widgets(ui_instance.main_window)
        
        # Connect double-click event to each table widget
        for table in table_widgets:
            if table:
                # Use lambda to pass the main_window to the handler
                table.itemDoubleClicked.connect(
                    lambda item, window=ui_instance.main_window: handle_table_double_click(window, item)
                )
        
    except Exception as e:
        print(f"[Error] Failed to connect double-click events: {str(e)}")
        import traceback
        traceback.print_exc()
        
def find_all_table_widgets(main_window):
    """Find all QTableWidget instances in the application
    
    Args:
        main_window: The main application window
        
    Returns:
        list: List of QTableWidget instances
    """
    try:
        table_widgets = []
        
        # Find all widgets that are QTableWidget instances
        for widget in main_window.findChildren(QtWidgets.QTableWidget):
            table_widgets.append(widget)
            
        return table_widgets
    except Exception as e:
        print(f"[Error] Failed to find table widgets: {str(e)}")
        import traceback
        traceback.print_exc()
        return []