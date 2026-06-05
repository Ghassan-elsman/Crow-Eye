"""
Virtual Table Widget for Crow Eye
Provides a truly virtualized table (QTableView + lazy QAbstractTableModel) that
loads rows on demand. Qt only requests data() for visible cells, so there is no
per-row item allocation — this scales smoothly to multi-million-row MFT/USN/SRUM
tables where the old QTableWidget + setRowCount(total) approach lagged badly.

Row data is fetched a small page at a time and addressed by an ordered rowid
index (seek by rowid, not LIMIT/OFFSET) so deep scrolling stays O(page) instead
of SQLite's O(offset).
"""

from PyQt5.QtWidgets import QTableView, QHeaderView, QAbstractItemView
from PyQt5.QtCore import pyqtSignal, Qt, QAbstractTableModel, QModelIndex
from typing import Optional, List, Dict, Any
import logging
import os
from array import array

from dynamic_mapping.enrichment.enrichment_mixin import EnrichmentMixin


class _LazyArtifactModel(QAbstractTableModel):
    """
    Lazy table model backing VirtualTableWidget.

    rowCount() reports the full total, but rows are only fetched (a page at a
    time) when Qt asks data() for them — i.e. only for visible cells. Pages are
    cached with simple LRU eviction so memory stays bounded while scrolling.
    All data-source state (table, columns, filter, order, enrichment) is read
    from the owning widget so there is a single source of truth.
    """

    PAGE = 256            # rows per fetched chunk (keeps rowid IN-lists small)
    MAX_CACHED_PAGES = 16  # ~4k rows kept resident

    def __init__(self, widget):
        super().__init__(widget)
        self.w = widget
        self._rowids = None        # array('q') of ordered rowids, or None
        self._total = 0
        self._cache: Dict[int, Any] = {}   # row_index -> record dict (or None)
        self._page_order: List[int] = []   # loaded page-start indices (LRU)

    # ------------------------------------------------------------------ Qt API
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else self._total

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.w.columns)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            labels = getattr(self.w, '_header_labels', None)
            if labels and 0 <= section < len(labels):
                return labels[section]
            if 0 <= section < len(self.w.columns):
                return self.w.columns[section]
            return None
        return str(section + 1)

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or role != Qt.DisplayRole:
            return None
        row = index.row()
        rec = self._cache.get(row)
        if rec is None:
            self._ensure_row(row)
            rec = self._cache.get(row)
            if rec is None:
                return None
        col_name = self.w.columns[index.column()]
        value = rec.get(col_name)
        text = "" if value is None else str(value)
        # Inline enrichment on the chosen column only.
        if col_name == self.w.enrichment_column:
            dyn = rec.get('Dynamic_Key')
            if dyn:
                try:
                    return self.w.format_enriched_value(text, dyn)
                except Exception:
                    return text
        return text

    # ---------------------------------------------------------------- loading
    def reload(self):
        """Rebuild the rowid index and reset the view."""
        self.beginResetModel()
        self._cache.clear()
        self._page_order.clear()
        self._rowids = None
        try:
            self._build_rowids()
            self._total = len(self._rowids)
        except Exception as e:
            self.w.logger.warning(
                f"rowid index build failed for '{self.w.table_name}'; "
                f"using OFFSET fallback: {e}"
            )
            self._rowids = None
            self._total = self._count_rows()
        self.endResetModel()

    def _count_rows(self) -> int:
        w = self.w
        try:
            if w.where_clause:
                q = f"SELECT COUNT(*) AS c FROM {w.table_name} WHERE {w.where_clause}"
                return int(w.data_loader.count_query(q, w.where_params))
            stats = w.data_loader.get_table_statistics(w.table_name)
            return int(stats.get('row_count', 0))
        except Exception:
            return 0

    def _build_rowids(self):
        """Fetch an ordered list of rowids once (integers only, compact)."""
        w = self.w
        conn = w.data_loader.connection
        cur = conn.cursor()
        order = w.order_by or 'rowid'
        sql = f"SELECT rowid FROM {w.table_name}"
        if w.where_clause:
            sql += f" WHERE {w.where_clause}"
        sql += f" ORDER BY {order}"
        cur.execute(sql, tuple(w.where_params) if w.where_params else [])
        self._rowids = array('q', (r[0] for r in cur))

    def _ensure_row(self, row: int):
        if row < 0 or row >= self._total:
            return
        start = (row // self.PAGE) * self.PAGE
        if start in self._page_order:
            return
        self._load_page(start)

    def _load_page(self, start: int):
        w = self.w
        end = min(start + self.PAGE, self._total)
        if end <= start:
            return
        # Quote identifiers so columns containing spaces / reserved words
        # (e.g. "Process Name") don't produce invalid SQL (which execute_query
        # would swallow, leaving the whole page blank).
        select_cols = ", ".join('"' + c + '"' for c in w.columns)
        enriched = bool(w.get_intelligence_db_path() and w.enrichment_column)
        try:
            if self._rowids is not None:
                # Seek by rowid: order comes from the rowid index slice (mapped
                # back via _vtw_rid), so this works for natural, custom-sorted
                # and filtered views alike regardless of SQL row order.
                chunk_ids = self._rowids[start:end]
                ids_csv = ",".join(str(int(r)) for r in chunk_ids)
                if enriched:
                    base = f"SELECT {select_cols}, rowid AS _vtw_rid FROM {w.table_name}"
                    query = w.get_enrichment_query(base, w.table_name, w.enrichment_column)
                    alias = f'"{w.table_name[:3]}_tbl"'
                    query += f" WHERE {alias}.rowid IN ({ids_csv})"
                else:
                    query = (
                        f"SELECT {select_cols}, rowid AS _vtw_rid "
                        f"FROM {w.table_name} WHERE rowid IN ({ids_csv})"
                    )
                rows = w.data_loader.execute_query(query, [])
                by_rid = {rec.get('_vtw_rid'): rec for rec in rows}
                for i, rid in enumerate(chunk_ids):
                    rec = by_rid.get(rid)
                    if rec is not None:
                        rec.pop('_vtw_rid', None)  # drop the rowid helper column
                    self._cache[start + i] = rec
            else:
                # Fallback: rowid index unavailable (rare — only if the rowid
                # scan failed). Page by OFFSET with the real filter + order.
                # Enrichment is sacrificed here so the filtered/ordered rows stay
                # correct; correctness of which rows appear beats enrichment.
                query = f"SELECT {select_cols} FROM {w.table_name}"
                if w.where_clause:
                    query += f" WHERE {w.where_clause}"
                if w.order_by:
                    query += f" ORDER BY {w.order_by}"
                query += f" LIMIT {end - start} OFFSET {start}"
                rows = w.data_loader.execute_query(query, w.where_params)
                for i, rec in enumerate(rows):
                    self._cache[start + i] = rec
        except Exception as e:
            w.logger.error(f"page load failed (start={start}) for '{w.table_name}': {e}")
            for i in range(start, end):
                self._cache.setdefault(i, None)

        # Register the page and evict the oldest to keep memory bounded.
        self._page_order.append(start)
        while len(self._page_order) > self.MAX_CACHED_PAGES:
            old = self._page_order.pop(0)
            for i in range(old, min(old + self.PAGE, self._total)):
                self._cache.pop(i, None)

    def record_at(self, row: int):
        rec = self._cache.get(row)
        if rec is None:
            self._ensure_row(row)
            rec = self._cache.get(row)
        return rec


class VirtualTableWidget(QTableView, EnrichmentMixin):
    """
    A QTableView-backed lazily-loaded table. Drop-in replacement for the former
    QTableWidget implementation: same constructor, signals, public methods and
    externally-read attributes, but truly virtualized for large datasets.
    """

    # Signals
    data_requested = pyqtSignal(int, int)  # offset, limit (kept for API compat)
    loading_started = pyqtSignal()
    loading_finished = pyqtSignal()
    data_loaded = pyqtSignal()  # Emitted when data is loaded and ready for styling

    # Enrichment Target Columns: Set of column names that should be enriched
    # If empty, the heuristic in _initialize_intelligence will try to pick the best ones.
    ENRICHMENT_TARGET_COLUMNS = {
        # --- File & Path Identifiers ---
        'target_path', 'Local_Path', 'Source_Name', 'Source_Path', 'executable_path',
        'key_path', 'program_path', 'app_path', 'file_path', 'folder_path', 'root_dir_path',
        'lower_case_long_path', 'process_path', 'image_path', 'ShortcutPath',
        'ShortcutTargetPath', 'mare_path', 'install_location', 'original_path',
        'recycle_bin_path', 'r_file_path', 'reconstructed_path', 'registry_path',
        'parent_path', 'Relative_Path', 'Working_Directory', 'Icon_Location',
        'Common_Path', 'manifest_path', 'package_full_name', 'bundle_manifest_path',
        'srudb_path', 'uninstall_string', 'path', 'folder_path', 'icon', 'ShortcutAumid',

        # --- User & System Identifiers ---
        'SID', 'user_sid', 'sid', 'User', 'username', 'user_name', 'Owner_UID',
        'registered_owner', 'ComputerName', 'computer_name', 'ComputerNameInfo',
        'Tracker_NetBIOS', 'ComputerName', 'registered_organization', 'product_id',
        'Owner_GID', 'owner_id', 'security_id', 'profile_image_path',

        # --- Network Identifiers ---
        'MAC_Address', 'gateway_mac', 'mac_address', 'dhcp_server', 'dns_servers',
        'network_name', 'server_name', 'share_name', 'interface_id', 'Tracker_MAC',
        'ip_address', 'network_share', 'interface_luid', 'l2_profile_id',
        'Birth_Object_ID_MAC', 'dhcp_server',

        # --- Hardware & Device Identifiers ---
        'device_id', 'instance_id', 'parent_id', 'serial_number', 'vendor_id',
        'product_id', 'volume_guid', 'model_id', 'class_guid', 'Device_ID',
        'Volume_Serial', 'Volume_Label', 'volume_name', 'Known_Folder_GUID',
        'Birth_Volume_ID', 'Birth_Object_ID', 'DestList_New_Volume_ID',
        'DestList_New_Object_ID', 'LNK_Class_ID', 'class_id', 'interface_luid',

        # --- Forensic & Process Identifiers ---
        'Value', 'Name', 'Filename', 'file_name', 'executable_name', 'fn_filename',
        'original_file_name', 'file_id', 'program_id', 'program_instance_id',
        'Process Name', 'app_name', 'program_name', 'service_name', 'display_name',
        'friendly_name', 'model_name', 'mare_name', 'search_term', 'command',
        'EventID', 'Source', 'TaskCategory', 'AppID',
        'entry_hash', 'original_filename',
        'random_i_filename', 'random_r_filename', 'ShortcutAumid', 'ShortcutProgramId',
        'driver_name', 'driver_id', 'mare_id', 'uup_id', 'uup_name', 'subkey_name',
        'folder_name', 'short_name',

        # --- Generic but Pattern-Heavy Columns ---
        'row_data', 'subkey', 'data', 'version', 'bin_file_version',
        'bin_product_version', 'display_version', 'driver_version', 'product_version'
    }

    # Identity / sequence columns that must NEVER be used as an enrichment target.
    # These hold incrementing integers (primary keys, MFT/USN record numbers) that
    # spuriously collide with numeric-valued mappings (e.g. Event-ID lookups),
    # producing meaningless "[Description not available]" enrichments.
    ENRICHMENT_EXCLUDED_COLUMNS = {
        'id', 'ID', 'rowid', 'ROWID', 'record_number', 'mft_record_number',
        'frn', 'parent_frn', 'parent_record', 'usn_event_id', 'offset',
    }

    def __init__(
        self,
        data_loader,
        table_name: str,
        columns: List[str],
        page_size: int = 1000,
        buffer_size: int = 2000,
        parent=None
    ):
        """
        Initialize virtual table widget.

        Args:
            data_loader: BaseDataLoader instance for database access
            table_name: Name of the database table
            columns: List of column names to display
            page_size: (retained for API compatibility; the lazy model uses its
                own small internal page size)
            buffer_size: (retained for API compatibility)
            parent: Parent widget
        """
        QTableView.__init__(self, parent)
        EnrichmentMixin.__init__(self)

        self.logger = logging.getLogger(self.__class__.__name__)

        # Data source configuration
        self.data_loader = data_loader
        self.table_name = table_name
        self.columns = columns
        self.page_size = page_size
        self.buffer_size = buffer_size

        # Enrichment configuration
        self.enrichment_column = None
        self._intelligence_initialized = False

        # Filter / sort state
        self.where_clause = None
        self.where_params = ()
        self.order_by = None

        # Data state
        self.total_rows = 0
        self.is_loading = False

        # Optional display labels for the horizontal header (set via
        # setHorizontalHeaderLabels). The model still uses `columns` for SQL.
        self._header_labels = None

        # Backing model
        self._model = _LazyArtifactModel(self)
        self.setModel(self._model)

        self._init_view()

    def _init_view(self):
        """Configure the view for fast, virtualized display."""
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setShowGrid(True)
        self.setSortingEnabled(False)  # ordering is server-side via set_order_by
        self.setWordWrap(False)
        self.setAttribute(Qt.WA_StyledBackground, True)

        # Smooth per-pixel scrolling to match the other artifact tables.
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)

        # Fixed-height rows => cheap geometry for huge row counts.
        vh = self.verticalHeader()
        vh.setSectionResizeMode(QHeaderView.Fixed)
        vh.setDefaultSectionSize(30)
        vh.setMinimumSectionSize(24)

        # Auto-fit columns to content (matches the other tables), but cap how
        # many rows ResizeToContents samples so it stays cheap on the lazy model.
        hh = self.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setStretchLastSection(True)
        hh.setMinimumSectionSize(80)
        hh.setSectionsClickable(True)
        hh.setHighlightSections(True)
        hh.setResizeContentsPrecision(50)

        self.doubleClicked.connect(self._on_double_clicked)

    def setHorizontalHeaderLabels(self, labels):
        """QTableWidget-compatible: set the display labels shown in the header.

        The model keeps using the real `columns` for SQL; only the visible
        header text changes. SRUM tabs call this to show friendly names.
        """
        self._header_labels = list(labels) if labels else None
        try:
            self._model.headerDataChanged.emit(Qt.Horizontal, 0, max(0, len(self.columns) - 1))
        except Exception:
            pass

    # ----------------------------------------------------------- data loading
    def load_initial_data(self) -> bool:
        """Detect enrichment, (re)build the model and refresh the view."""
        try:
            self.loading_started.emit()
            self.is_loading = True

            stats = self.data_loader.get_table_statistics(self.table_name)
            if not stats.get('table_exists', False):
                self.logger.error(f"Table '{self.table_name}' does not exist.")
                self._model.reload()
                self.total_rows = 0
                return False

            # Intelligence Integration
            if not self._intelligence_initialized:
                self._initialize_intelligence()

            # Re-attach intelligence DB so enriched page queries can see Intel.*
            if self.get_intelligence_db_path():
                try:
                    cursor = self.data_loader.connection.cursor()
                    self.attach_intelligence_db(cursor)
                    self.logger.info(f"Attached intelligence brain to {self.table_name} view.")
                except Exception as attach_err:
                    self.logger.error(f"Failed to attach intelligence: {attach_err}")

            self._model.reload()
            self.total_rows = self._model.rowCount()

            self._apply_styles_immediately()
            self.data_loaded.emit()
            return True

        except Exception as e:
            self.logger.error(f"Error loading initial data: {e}")
            return False
        finally:
            self.is_loading = False
            self.loading_finished.emit()

    def refresh_data(self) -> bool:
        """Reload from the database (re-detecting enrichment if reset)."""
        try:
            return self.load_initial_data()
        except Exception as e:
            self.logger.error(f"Error refreshing data: {e}")
            return False

    def apply_filter(self, where_clause: str, where_params: tuple = ()) -> bool:
        """Apply a WHERE filter and reload."""
        try:
            self.where_clause = where_clause
            self.where_params = where_params
            return self.load_initial_data()
        except Exception as e:
            self.logger.error(f"Error applying filter: {e}")
            return False

    def clear_filter(self) -> bool:
        """Clear any applied filter and reload."""
        try:
            self.where_clause = None
            self.where_params = ()
            return self.load_initial_data()
        except Exception as e:
            self.logger.error(f"Error clearing filter: {e}")
            return False

    def set_order_by(self, order_by: Optional[str]):
        """Set the ORDER BY clause (applied on the next load)."""
        self.order_by = order_by

    def get_total_rows(self) -> int:
        return self.total_rows

    def get_loaded_row_count(self) -> int:
        return len(self._model._cache)

    def get_selected_records(self) -> List[Dict[str, Any]]:
        """Return the full DB records for the selected rows."""
        records: List[Dict[str, Any]] = []
        try:
            rows = sorted({idx.row() for idx in self.selectionModel().selectedRows()})
            for row_index in rows:
                rec = self._model.record_at(row_index)
                if rec is not None:
                    records.append(rec)
            return records
        except Exception as e:
            self.logger.error(f"Error getting selected records: {e}")
            return []

    def _apply_styles_immediately(self):
        """Apply Crow Eye styles, keeping columns Interactive (not ResizeToContents)."""
        try:
            from styles import CrowEyeStyles
            CrowEyeStyles.apply_table_styles(self)
        except Exception as e:
            self.logger.error(f"Error applying styles: {e}")
        # apply_table_styles sets ResizeToContents (matching the other tables);
        # just cap the sampling so auto-fit stays fast on the lazy model.
        try:
            self.horizontalHeader().setResizeContentsPrecision(50)
        except Exception:
            pass

    # ------------------------------------------------------------- row detail
    def _on_double_clicked(self, index: QModelIndex):
        """Open the row-detail dialog for the double-clicked row."""
        try:
            if not index.isValid():
                return
            from ui.row_detail_dialog import RowDetailDialog

            row = index.row()
            row_data = self._model.record_at(row)
            if not row_data:
                self.logger.warning(f"No data found for row {row}")
                return

            # Determine Row Name (heuristic)
            row_name = "Unknown Row"
            name_keys = ["Name", "Filename", "Executable Name", "Process Name", "Service Name", "Device Name", "User", "Key", "app_name", "folder_name"]
            for key in name_keys:
                for data_key in row_data.keys():
                    if data_key.lower() == key.lower() and row_data[data_key]:
                        row_name = str(row_data[data_key])
                        break
                if row_name != "Unknown Row":
                    break

            # Fallback: use the first available value if no priority key found
            if row_name == "Unknown Row" and row_data:
                first_value = next(iter(row_data.values()))
                if first_value:
                    row_name = str(first_value)

            row_number = row + 1
            display_name = self.table_name.replace('_', ' ').title()

            dialog = RowDetailDialog(row_data, display_name, row_name, row_number, self.parent())
            dialog.show()

        except Exception as e:
            self.logger.error(f"Error showing row detail dialog: {e}")
            import traceback
            traceback.print_exc()

    def set_intelligence_db_path(self, case_directory: str):
        """
        Manually set the path to the intelligence database.

        Args:
            case_directory: Root directory of the case
        """
        intel_db = os.path.join(case_directory, "Crow_Intelligence.db")
        if os.path.exists(intel_db):
            super().set_intelligence_db_path(case_directory)
            self._intelligence_initialized = True
            if self.data_loader and self.data_loader.connection:
                try:
                    cursor = self.data_loader.connection.cursor()
                    self.attach_intelligence_db(cursor)
                    self.logger.info(f"Attached intelligence brain from {intel_db}")
                except Exception as e:
                    self.logger.error(f"Failed to attach intelligence: {e}")
        else:
            self.logger.warning(f"Intelligence database not found at {intel_db}")

    def _initialize_intelligence(self):
        """
        Detect Crow_Intelligence.db and set up enrichment targets.

        Searches recursively upwards from the artifact directory to find the case root
        where Crow_Intelligence.db resides.
        """
        try:
            if not (hasattr(self.data_loader, 'db_path') and self.data_loader.db_path):
                self._intelligence_initialized = True
                return

            # --- 1. Recursive Brain Discovery ---
            current_dir = os.path.dirname(str(self.data_loader.db_path))
            intel_db_path = None
            intel_case_root = None

            # Search upwards (max 5 levels for sanity) to find the case root
            for _ in range(5):
                candidate = os.path.join(current_dir, "Crow_Intelligence.db")
                if os.path.exists(candidate):
                    intel_db_path = candidate
                    intel_case_root = current_dir
                    break

                parent = os.path.dirname(current_dir)
                if parent == current_dir:  # Reached drive root
                    break
                current_dir = parent

            if not intel_db_path:
                self.logger.debug("No Crow_Intelligence.db found in recursive upward search.")
                self._intelligence_initialized = True
                return

            self.set_intelligence_db_path(intel_case_root)
            self.logger.info(f"Recursive Discovery: Found intelligence at {intel_db_path}")

            # --- 2. Forensic Priority Heuristic ---
            # We prioritize identity-bearing columns because they have the highest
            # intelligence value (e.g. mapping a SID to "Admin" is better than mapping a Filename).
            priority_groups = [
                # Tier 1: Identity (Most Valuable)
                ['user_sid', 'SID', 'sid', 'security_id', 'MAC_Address', 'mac_address', 'gateway_mac', 'ip_address', 'IP_Address'],
                # Tier 2: Device/HW
                ['device_id', 'serial_number', 'volume_serial', 'volume_guid', 'instance_id'],
                # Tier 3: Process/App
                ['app_name', 'service_name', 'executable_name', 'Process Name', 'app_id', 'AppID'],
                # Tier 4: Files/Paths (Least specific, often collisions)
                ['Filename', 'file_name', 'filename', 'target_path', 'path', 'Local_Path', 'key_path']
            ]

            found_target = False
            for group in priority_groups:
                for candidate in group:
                    # Check if this priority candidate is in our table columns
                    if candidate in self.columns and candidate not in self.ENRICHMENT_EXCLUDED_COLUMNS:
                        self.enrichment_column = candidate
                        self.logger.info(f"Heuristic Match: Prioritizing Tier {priority_groups.index(group)+1} column '{candidate}'")
                        found_target = True
                        break
                if found_target:
                    break

            # Final Fallback: Set match
            if not found_target:
                for col in self.columns:
                    if col in self.ENRICHMENT_EXCLUDED_COLUMNS:
                        continue
                    if col in self.ENRICHMENT_TARGET_COLUMNS:
                        self.enrichment_column = col
                        found_target = True
                        break

            self._intelligence_initialized = True

        except Exception as e:
            self.logger.error(f"Failed to initialize intelligence brain: {e}")
            self._intelligence_initialized = True
