"""
Dynamic Linking Window GUI for the Intelligence Engine.

This module provides the main GUI window for managing intelligence mappings
through three distinct sections: Intelligence Gathering, Bulk IOC Ingestion, and Live Mapping.
"""

import os
import csv
import json
import logging
import sqlite3
from typing import Optional, List, Dict, Tuple

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QWidget, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QLineEdit,
    QComboBox, QFrame, QFileDialog, QTextEdit, QCheckBox,
    QHeaderView, QMessageBox, QAbstractItemView, QProgressBar,
    QMenu, QAction
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5 import QtCore, QtGui

from dynamic_mapping.core.intelligence_engine import IntelligenceEngine
from styles import CrowEyeStyles, Colors
from ui.Loading_dialog import LoadingDialog

logger = logging.getLogger(__name__)

class CascadingSelectButton(QPushButton):
    """
    A unified button that handles DB -> Table -> Column selection via a hierarchical menu.
    """
    selectionChanged = pyqtSignal(str, str, str) # db, table, column

    def __init__(self, placeholder="Select Source...", parent=None):
        super().__init__(placeholder, parent)
        self.placeholder = placeholder
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {Colors.BG_TABLES};
                color: {Colors.TEXT_PRIMARY};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: 5px;
                padding: 8px;
                text-align: left;
                font-family: 'Consolas';
                font-size: 11px;
            }}
            QPushButton:hover {{
                border: 1px solid {Colors.ACCENT_CYAN};
                background-color: rgba(0, 255, 255, 0.05);
            }}
        """)
        self.setCursor(Qt.PointingHandCursor)
        
        self.selected_db = None
        self.selected_table = None
        self.selected_column = None
        
        self.clicked.connect(self.show_hierarchy_menu)

    def set_data(self, db_schema: Dict[str, Dict[str, List[str]]]):
        """
        db_schema: { 'db_name': { 'table_name': ['col1', 'col2'] } }
        """
        self.db_schema = db_schema

    def show_hierarchy_menu(self):
        if not hasattr(self, 'db_schema') or not self.db_schema:
            QMessageBox.warning(self, "No Data", "No database artifacts found in case directory.")
            return

        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {Colors.BG_PANELS};
                color: {Colors.TEXT_PRIMARY};
                border: 1px solid {Colors.ACCENT_CYAN};
            }}
            QMenu::item:selected {{
                background-color: {Colors.ACCENT_BLUE};
            }}
        """)

        for db_name, tables in self.db_schema.items():
            db_menu = menu.addMenu(db_name)
            for table_name, columns in tables.items():
                table_menu = db_menu.addMenu(table_name)
                for col_name in columns:
                    action = table_menu.addAction(col_name)
                    # Use closure to capture names
                    action.triggered.connect(lambda checked, d=db_name, t=table_name, c=col_name: 
                                           self.on_final_selection(d, t, c))

        menu.exec_(self.mapToGlobal(self.rect().bottomLeft()))

    def on_final_selection(self, db, table, col):
        self.selected_db = db
        self.selected_table = table
        self.selected_column = col
        self.setText(f"{db} > {table} > {col}")
        self.selectionChanged.emit(db, table, col)

class DynamicLinkingWindow(QDialog):
    """
    Main GUI window for Dynamic Linking Intelligence Engine.
    
    3-Section Grid Layout:
    - [Top-Left]: Gathering & Manual Entry (Hierarchical Selectors)
    - [Bottom-Left]: Bulk IOC Ingestion (Drag-Drop / File)
    - [Right]: Live Mapping Table (Real-time View)
    """
    
    def __init__(self, case_directory: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.case_directory = case_directory
        self.engine = IntelligenceEngine(case_directory)
        
        self.setWindowTitle("Crow-Eye | Dynamic Linking Intelligence")
        self.setMinimumSize(1300, 850)
        
        # Set Window Icon
        self.setWindowIcon(QtGui.QIcon("GUI Resources/icons/dynamic_linking.svg"))
        
        # Enable Min/Max buttons
        self.setWindowFlags(self.windowFlags() | Qt.WindowMinMaxButtonsHint | Qt.WindowMaximizeButtonHint)
        
        self.setStyleSheet(CrowEyeStyles.DYNAMIC_LINKING_WINDOW_STYLE)
        
        self.db_schema_cache = {}
        
        # --- Persistence Check: Verify database initialization ---
        if not self.engine.ensure_db():
            logger.error("Failed to initialize intelligence database.")
            
        self._init_ui()
        self._load_schema_and_data()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(25, 25, 25, 25)
        main_layout.setSpacing(20)

        # 1. Header
        header = QHBoxLayout()
        title = QLabel("DYNAMIC LINKING INTELLIGENCE")
        title.setStyleSheet(f"font-size: 22px; font-weight: 900; color: {Colors.ACCENT_CYAN}; letter-spacing: 3px;")
        header.addWidget(title)
        header.addStretch()
        self.stats_label = QLabel("Total Mappings: 0")
        self.stats_label.setStyleSheet(f"font-weight: bold; color: {Colors.TEXT_SECONDARY}; font-size: 14px;")
        header.addWidget(self.stats_label)
        main_layout.addLayout(header)

        # 2. Central Content (Left Stack | Right Table)
        content_layout = QHBoxLayout()
        content_layout.setSpacing(25)

        # --- LEFT STACK (Gathering + Ingestion) ---
        left_stack = QVBoxLayout()
        left_stack.setSpacing(20)

        # Top-Left: Gathering
        self.gathering_box = self._setup_gathering_section()
        left_stack.addWidget(self.gathering_box, 3)

        # Bottom-Left: Ingestion
        self.ingestion_box = self._setup_ingestion_section()
        left_stack.addWidget(self.ingestion_box, 2)

        content_layout.addLayout(left_stack, 2)

        # --- RIGHT PANEL (Live Table) ---
        self.mapping_box = self._setup_mapping_section()
        content_layout.addWidget(self.mapping_box, 3)

        main_layout.addLayout(content_layout)

        # 3. Footer (Progress + Run)
        footer = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedHeight(25)
        self.progress_bar.setStyleSheet(CrowEyeStyles.LOADING_PROGRESS)
        footer.addWidget(self.progress_bar)

        run_btn = QPushButton("RUN DYNAMIC LINKING")
        run_btn.setFixedWidth(280)
        run_btn.setFixedHeight(50)
        run_btn.setStyleSheet(CrowEyeStyles.SUCCESS_BUTTON)
        run_btn.clicked.connect(self._run_final_linking)
        footer.addSpacing(30)
        footer.addWidget(run_btn)
        main_layout.addLayout(footer)

    def _setup_gathering_section(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.BG_PANELS};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: 10px;
            }}
        """)
        layout = QVBoxLayout(frame)
        layout.setSpacing(15)

        title = QLabel("1. INTELLIGENCE GATHERING")
        title.setStyleSheet(f"font-weight: 800; color: {Colors.ACCENT_CYAN}; font-size: 15px; border: none;")
        layout.addWidget(title)

        # Active Rules
        layout.addWidget(QLabel("Pre-configured Extraction Pipelines:"))
        self.rules_display = QTextEdit()
        self.rules_display.setReadOnly(True)
        self.rules_display.setFixedHeight(120)
        self.rules_display.setStyleSheet(f"""
            QTextEdit {{
                background-color: {Colors.BG_TABLES};
                background-image: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(0, 255, 255, 0.05), stop:1 rgba(0, 0, 0, 0));
                border: 1px solid {Colors.ACCENT_CYAN};
                border-radius: 5px;
                padding: 10px;
                color: {Colors.TEXT_PRIMARY};
                font-family: 'Consolas';
                font-size: 12px;
            }}
        """)
        layout.addWidget(self.rules_display)

        # Custom Mapping Row
        layout.addWidget(QLabel("Manual Relationship Definition:"))
        manual_row = QVBoxLayout()
        manual_row.setSpacing(10)
        
        # Value Selector
        val_label = QLabel("SOURCE ARTIFACT (VALUE):")
        val_label.setStyleSheet("font-size: 10px; color: #94A3B8;")
        manual_row.addWidget(val_label)
        self.value_selector = CascadingSelectButton("Select Database > Table > Value Column...")
        manual_row.addWidget(self.value_selector)

        # Key Selector
        key_label = QLabel("CONTEXT PROVIDER (KEY):")
        key_label.setStyleSheet("font-size: 10px; color: #94A3B8;")
        manual_row.addWidget(key_label)
        self.key_selector = CascadingSelectButton("Select Database > Table > Key Column...")
        manual_row.addWidget(self.key_selector)

        layout.addLayout(manual_row)

        # Inline note that explains the same-DB/same-table requirement for the
        # manual rule. Updated dynamically by _refresh_manual_rule_state().
        self.manual_rule_hint = QLabel("")
        self.manual_rule_hint.setStyleSheet("font-size: 10px; color: #f59e0b;")
        self.manual_rule_hint.setVisible(False)
        layout.addWidget(self.manual_rule_hint)

        btn_row = QHBoxLayout()

        self.gather_btn = QPushButton("LINK GATHERING")
        self.gather_btn.setStyleSheet(CrowEyeStyles.DYNAMIC_LINK_BUTTON)
        self.gather_btn.setFixedHeight(40)
        self.gather_btn.clicked.connect(self._run_link_gathering)
        btn_row.addWidget(self.gather_btn)

        layout.addLayout(btn_row)

        # Re-evaluate the gather button when either manual selector changes so
        # the user sees the disabled state + hint before pressing the button
        # (instead of after, when _process_manual_rule would silently warn).
        self.value_selector.selectionChanged.connect(lambda *_: self._refresh_manual_rule_state())
        self.key_selector.selectionChanged.connect(lambda *_: self._refresh_manual_rule_state())

        return frame

    def _setup_ingestion_section(self) -> QFrame:
        frame = QFrame()
        layout = QVBoxLayout(frame)

        title = QLabel("2. BULK IOC INGESTION")
        title.setStyleSheet(f"font-weight: 800; color: {Colors.ACCENT_CYAN}; font-size: 15px;")
        layout.addWidget(title)

        self.drop_area = QTextEdit()
        self.drop_area.setPlaceholderText("DRAG & DROP IOC FEED\nSupport: .csv, .json mapping pairs")
        self.drop_area.setFixedHeight(80)
        self.drop_area.setAcceptDrops(True)
        self.drop_area.dragEnterEvent = self._drag_enter_event
        self.drop_area.dropEvent = self._drop_event
        layout.addWidget(self.drop_area)

        browse_row = QHBoxLayout()
        self.ioc_type = QComboBox()
        self.ioc_type.addItems(["Auto-Detect", "Hash", "IP", "Domain"])
        browse_row.addWidget(self.ioc_type)

        browse_btn = QPushButton("BROWSE FILES")
        browse_btn.setStyleSheet(CrowEyeStyles.ORANGE_BUTTON)
        browse_btn.clicked.connect(self._browse_ioc)
        browse_row.addWidget(browse_btn)
        layout.addLayout(browse_row)

        self.ingest_log = QTextEdit()
        self.ingest_log.setReadOnly(True)
        self.ingest_log.setFixedHeight(80)
        self.ingest_log.setStyleSheet(f"color: {Colors.SUCCESS}; font-family: Consolas; font-size: 11px;")
        layout.addWidget(self.ingest_log)

        return frame

    def _setup_mapping_section(self) -> QFrame:
        frame = QFrame()
        layout = QVBoxLayout(frame)

        title = QLabel("3. LIVE INTELLIGENCE REGISTRY")
        title.setStyleSheet(f"font-weight: 800; color: {Colors.ACCENT_CYAN}; font-size: 15px;")
        layout.addWidget(title)

        # Search / Filter
        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search mappings by value or context...")
        self.search_input.textChanged.connect(self._filter_table)
        search_row.addWidget(self.search_input)
        
        refresh_btn = QPushButton("REFRESH")
        refresh_btn.setStyleSheet(CrowEyeStyles.BUTTON_STYLE)
        refresh_btn.clicked.connect(self._load_mappings_into_table)
        search_row.addWidget(refresh_btn)
        layout.addLayout(search_row)

        # The Mapping Table
        self.mappings_table = QTableWidget()
        self.mappings_table.setColumnCount(3)
        self.mappings_table.setHorizontalHeaderLabels(["RAW ARTIFACT", "MAPPED CONTEXT", "SOURCE ORIGIN"])
        CrowEyeStyles.apply_table_styles(self.mappings_table)
        self.mappings_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.mappings_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self.mappings_table)

        # Table Actions
        act_row = QHBoxLayout()
        del_btn = QPushButton("DELETE SELECTION")
        del_btn.setStyleSheet(CrowEyeStyles.RED_BUTTON)
        del_btn.clicked.connect(self._delete_mappings)
        act_row.addWidget(del_btn)

        export_btn = QPushButton("EXPORT CASE INTEL")
        export_btn.setStyleSheet(CrowEyeStyles.EXPORT_BUTTON)
        export_btn.clicked.connect(self._export_case_intel)
        act_row.addWidget(export_btn)
        layout.addLayout(act_row)

        return frame

    def _load_schema_and_data(self):
        """Fetch DB schema for cascading selectors and populate initial table."""
        from dynamic_mapping.rules.default_rules import DEFAULT_RULES
        
        # 1. Load Rules Display
        text = "\n".join([f"• {name}" for name in DEFAULT_RULES.keys()])
        self.rules_display.setPlainText(text)

        # 2. Build Schema Cache
        artifacts_dir = self.engine._find_artifacts_directory()
        if artifacts_dir:
            dbs = [f for f in os.listdir(artifacts_dir) if f.endswith('.db')]
            failed = []
            for db in dbs:
                db_path = os.path.join(artifacts_dir, db)
                try:
                    conn = sqlite3.connect(db_path)
                    cursor = conn.cursor()
                    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                    tables = {}
                    for t_name in [r[0] for r in cursor.fetchall() if not r[0].startswith('sqlite_')]:
                        cursor.execute(f"PRAGMA table_info({t_name})")
                        tables[t_name] = [r[1] for r in cursor.fetchall()]
                    self.db_schema_cache[db] = tables
                    conn.close()
                except Exception as e:
                    # Don't silently lose a known DB from the cascading selector.
                    # The investigator should see WHY a DB is missing from the
                    # dropdown (locked / corrupt / schema issue).
                    logger.warning("Failed to read schema from %s: %s", db, e)
                    failed.append(f"{db}: {e}")
            if failed and hasattr(self, "ingest_log"):
                self.ingest_log.append("[Schema] Could not read:\n" + "\n".join(failed))

        self.value_selector.set_data(self.db_schema_cache)
        self.key_selector.set_data(self.db_schema_cache)

        # 3. Initial Table Load
        self._load_mappings_into_table()

    def _run_link_gathering(self):
        """Execute intelligence gathering with a properly-managed loading dialog."""
        from ui.Loading_dialog import LoadingDialog
        from dynamic_mapping.rules.default_rules import DEFAULT_RULES
        from PyQt5.QtWidgets import QApplication

        if not self.engine.ensure_db():
            QMessageBox.critical(self, "Critical Error", "Failed to access intelligence database.")
            return

        # Surface the most common silent failure: no artifacts directory means
        # every database-backed rule will skip, and the user otherwise sees a
        # successful run that found 0 mappings with no explanation.
        if not self.engine._find_artifacts_directory():
            QMessageBox.warning(
                self,
                "No Artifacts Found",
                "No forensic artifacts were detected in this case.\n\n"
                "Dynamic Linking needs at least one of:\n"
                "  • a Target_Artifacts/ directory with .db files, or\n"
                "  • a live_acquisition/ directory with .db files, or\n"
                "  • .db files in the case root.\n\n"
                "Internal rules (e.g. Well-Known SIDs) will still run, but most\n"
                "default rules cannot extract mappings without artifacts."
            )

        loading = LoadingDialog("Gathering Intelligence", self)

        # Build steps dynamically to ensure the progress bar updates accurately for each rule
        steps = ["Initializing Engine..."]
        
        rules = list(DEFAULT_RULES.keys())
        for rule_name in rules:
            display_name = rule_name.replace('_', ' ').title()
            steps.append(f"Running rule: {display_name}")
            
        steps.append("Processing Custom Rules...")

        # Check for manual rule
        has_manual = (
            bool(self.value_selector.selected_db) and
            bool(self.key_selector.selected_db)
        )
        if has_manual:
            steps.append("Processing Manual Relationship...")

        loading.set_steps(steps)

        # ---------------------  Work runs before exec_()  ---------------------
        # We do the work while the dialog is visible (show()), keep the event
        # loop alive via processEvents(), and then drive exec_() only for the
        # 2-second completion pause so the timer-based accept() actually fires.
        loading.show()
        QApplication.processEvents()

        loading.update_step(0, "Scanning artifact directories...")
        QApplication.processEvents()

        # 1. Default Rules
        total_found = 0
        step_idx = 1

        # Make sure the engine is ready for action
        self.engine.ensure_db()

        cancelled = False
        for rule_name in rules:
            if loading.is_cancelled():
                loading.add_log_message("[Aborted] Operation cancelled by user.")
                cancelled = True
                break
            
            display_name = rule_name.replace('_', ' ').title()
            loading.update_step(step_idx, f"Extracting {display_name}...")
            step_idx += 1
            
            loading.add_log_message(f"Running rule: {rule_name}")
            # Process Qt events so the loading dialog stays responsive
            QApplication.processEvents()
            # custom_rules=False: run only this default rule. Custom rules are run
            # ONCE after the loop (below) instead of being re-executed on every
            # default-rule iteration.
            res = self.engine.gather_intelligence([rule_name], custom_rules=False)
            found_for_rule = sum(res.values())
            total_found += found_for_rule
            if found_for_rule > 0:
                loading.add_log_message(f"[Success] Found {found_for_rule} mappings for {rule_name}")
            QApplication.processEvents()

        # Custom rules: execute exactly once, after all default rules.
        if not cancelled:
            loading.update_step(step_idx, "Executing custom intelligence pipelines...")
            step_idx += 1
            
            loading.add_log_message("Running custom rules...")
            QApplication.processEvents()
            custom_res = self.engine.gather_intelligence([], custom_rules=True)
            custom_found = sum(custom_res.values())
            total_found += custom_found
            if custom_found > 0:
                loading.add_log_message(f"[Success] Found {custom_found} mappings from custom rules")
            QApplication.processEvents()

        # 2. Manual Rule
        if has_manual and not loading.is_cancelled():
            loading.update_step(step_idx, "Extracting manual relationship data...")
            step_idx += 1
            manual_count = self._process_manual_rule(loading)
            total_found += manual_count

        # Completion summary
        loading.add_log_message(f"[Intelligence] Total unique mappings found: {total_found}")
        loading.show_completion(f"SUCCESS: {total_found} forensic relationships integrated.")
        QApplication.processEvents()

        # Auto-close after 2 seconds using exec_() so the QTimer can fire.
        # The dialog is already visible (show() was called above); exec_() just
        # takes ownership of the event loop for the brief completion pause.
        QTimer.singleShot(2000, loading.accept)
        loading.exec_()

        # Update the live table and status bar AFTER the dialog closes.
        self.ingest_log.setPlainText(
            f"SYSTEM SCAN COMPLETE\n---------------------\nFound {total_found} forensic relationships."
        )
        print(f"[IntelligenceEngine] Scan complete. Found {total_found} relationships.")
        self._load_mappings_into_table()

    def _process_manual_rule(self, loading) -> int:
        """Extract data for manual relationship definition."""
        val_db = self.value_selector.selected_db
        val_table = self.value_selector.selected_table
        val_col = self.value_selector.selected_column
        
        key_db = self.key_selector.selected_db
        key_table = self.key_selector.selected_table
        key_col = self.key_selector.selected_column
        
        artifacts_dir = self.engine._find_artifacts_directory()
        if not artifacts_dir: return 0
        
        count = 0
        try:
            if val_db == key_db and val_table == key_table:
                db_path = os.path.join(artifacts_dir, val_db)
                loading.add_log_message(f"Extracting from {val_db} > {val_table}")
                
                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(f'SELECT "{val_col}", "{key_col}" FROM "{val_table}"')
                rows = cursor.fetchall()
                
                for row in rows:
                    if loading.is_cancelled(): break
                    v = row[val_col]
                    k = row[key_col]
                    if v and k:
                        if self.engine.add_mapping(str(v), str(k), "Manual Selection"):
                            count += 1
                conn.close()
            else:
                loading.add_log_message("[Warning] Cross-table manual linking not yet supported. Please select columns from the same table.")
        except Exception as e:
            loading.add_log_message(f"[Error] Manual linking failed: {str(e)}")
            
        return count

    def _run_final_linking(self):
        """Finalize and apply intelligence to the current case."""
        mappings = self.engine.get_all_mappings()

        if not mappings:
            print("[IntelligenceEngine] No existing mappings found. Starting automated discovery...")
            # _run_link_gathering manages its own loading dialog end-to-end.
            self._run_link_gathering()
        else:
            # Mappings already exist — show a brief refresh confirmation.
            from ui.Loading_dialog import LoadingDialog
            from PyQt5.QtWidgets import QApplication
            loading = LoadingDialog("Refreshing Intelligence", self)
            loading.set_steps(["Synchronizing Case Context..."])
            loading.show()
            QApplication.processEvents()
            loading.update_step(0, "Updating intelligence mappings in view...")
            loading.show_completion("Intelligence synchronization complete.")
            QApplication.processEvents()
            # Auto-close after 1.5 s via exec_() so the timer can fire.
            QTimer.singleShot(1500, loading.accept)
            loading.exec_()

        # Signal main application and close
        print("[Info] Finalizing dynamic linking. All systems go.")
        self.accept()

    def _load_mappings_into_table(self):
        # Prefer the source-bearing accessor so the SOURCE ORIGIN column reflects
        # actual provenance (UserProfiles / IOC_File / Manual Selection / ...).
        if hasattr(self.engine, "get_all_mappings_with_source"):
            rows = self.engine.get_all_mappings_with_source()
        else:  # Back-compat fallback
            rows = [(v, k, "") for v, k in self.engine.get_all_mappings().items()]

        self.mappings_table.setUpdatesEnabled(False)
        self.mappings_table.blockSignals(True)
        try:
            self.mappings_table.setRowCount(0)
            self.mappings_table.setRowCount(len(rows))

            for i, (val, key, source) in enumerate(rows):
                self.mappings_table.setItem(i, 0, QTableWidgetItem(str(val)))
                self.mappings_table.setItem(i, 1, QTableWidgetItem(str(key)))
                self.mappings_table.setItem(i, 2, QTableWidgetItem(str(source or "")))
        finally:
            self.mappings_table.blockSignals(False)
            self.mappings_table.setUpdatesEnabled(True)
            self.mappings_table.viewport().update()

        self.stats_label.setText(f"Total Mappings: {len(rows)}")

    def _filter_table(self, text):
        needle = (text or "").lower()
        col_count = self.mappings_table.columnCount()
        
        self.mappings_table.setUpdatesEnabled(False)
        self.mappings_table.blockSignals(True)
        try:
            for row in range(self.mappings_table.rowCount()):
                match = False
                for col in range(col_count):
                    item = self.mappings_table.item(row, col)
                    if item and needle in item.text().lower():
                        match = True
                        break
                self.mappings_table.setRowHidden(row, not match)
        finally:
            self.mappings_table.blockSignals(False)
            self.mappings_table.setUpdatesEnabled(True)
            self.mappings_table.viewport().update()

    def _delete_mappings(self):
        selected = self.mappings_table.selectedItems()
        if not selected: return
        rows = set(item.row() for item in selected)
        for row in sorted(rows, reverse=True):
            val = self.mappings_table.item(row, 0).text()
            self.engine.delete_mapping(val)
        self._load_mappings_into_table()

    def _drag_enter_event(self, event):
        if event.mimeData().hasUrls(): event.acceptProposedAction()

    def _drop_event(self, event):
        ioc_type = self._selected_ioc_type()
        for url in event.mimeData().urls():
            self.engine.ingest_ioc_file(url.toLocalFile(), ioc_type=ioc_type)
        self._load_mappings_into_table()

    def _browse_ioc(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open IOC Intel Feed", "", "Data (*.csv *.json)")
        if path:
            self.engine.ingest_ioc_file(path, ioc_type=self._selected_ioc_type())
            self._load_mappings_into_table()

    def _selected_ioc_type(self) -> str:
        """Map the IOC type combo to the engine's ioc_type string.

        "Auto-Detect" → "auto"; everything else is lower-cased so the engine can
        use it directly as the Mapping.source value (e.g. "hash", "ip", "domain").
        """
        try:
            label = self.ioc_type.currentText().strip()
        except Exception:
            return "auto"
        if not label or label.lower().startswith("auto"):
            return "auto"
        return label.lower()

    def _refresh_manual_rule_state(self) -> None:
        """Enable / disable LINK GATHERING based on whether the two manual
        selectors point at the same DB and table. Cross-table linking is not
        implemented in the backend, so we surface the requirement up-front
        instead of letting the user press the button and get a silent warning."""
        v_db = self.value_selector.selected_db
        v_tbl = self.value_selector.selected_table
        k_db = self.key_selector.selected_db
        k_tbl = self.key_selector.selected_table

        # If either side is incomplete, the manual rule is just skipped on
        # press — leave the button enabled so default rules can still run.
        if not (v_db and v_tbl and k_db and k_tbl):
            self.manual_rule_hint.setVisible(False)
            self.gather_btn.setEnabled(True)
            return

        if v_db != k_db or v_tbl != k_tbl:
            self.manual_rule_hint.setText(
                "Manual link requires both selectors to point at the same DB and table — change one to match."
            )
            self.manual_rule_hint.setVisible(True)
            self.gather_btn.setEnabled(False)
        else:
            self.manual_rule_hint.setVisible(False)
            self.gather_btn.setEnabled(True)

    def _export_case_intel(self) -> None:
        """Write every mapping in this case to CSV or JSON.

        Format follows the convention used by DatabaseSearchDialog._export_to_csv/_export_to_json:
        QFileDialog for the path, then write headers + rows. JSON yields a list of
        dicts so it can be consumed by downstream tooling without parsing.
        """
        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export Case Intelligence",
            "case_intelligence",
            "CSV (*.csv);;JSON (*.json)",
        )
        if not path:
            return

        rows = self.engine.get_all_mappings_with_source() if hasattr(
            self.engine, "get_all_mappings_with_source"
        ) else [(v, k, "") for v, k in self.engine.get_all_mappings().items()]

        ext = os.path.splitext(path)[1].lower()
        if not ext:
            ext = ".json" if "JSON" in (selected_filter or "") else ".csv"
            path += ext

        try:
            if ext == ".json":
                payload = [{"value": v, "key": k, "source": s} for (v, k, s) in rows]
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(payload, f, indent=2, ensure_ascii=False)
            else:
                with open(path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(["value", "key", "source"])
                    for v, k, s in rows:
                        writer.writerow([v, k, s])
            QMessageBox.information(
                self,
                "Export Complete",
                f"Exported {len(rows)} mapping(s) to:\n{path}",
            )
        except Exception as e:
            logger.exception("Failed to export case intelligence")
            QMessageBox.critical(self, "Export Failed", f"Could not write {path}:\n{e}")

    def closeEvent(self, event):
        """Release the engine's sqlite connection so repeat open/close doesn't
        leak file handles to Crow_Intelligence.db."""
        try:
            if hasattr(self, "engine") and self.engine is not None:
                self.engine.cleanup()
        except Exception:
            logger.exception("DynamicLinkingWindow.closeEvent: engine cleanup failed")
        super().closeEvent(event)
