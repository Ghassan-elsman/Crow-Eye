"""Row details: one record of an artifact table, field by field.

Opened by a double-click on a row in the main window's tables (both the plain
and the virtual ones), by the Timeline, UBA and Database Search. Several can
be open at once, side by side, for comparison.

The grouping is the one the dialog always had - File Info, Timestamps and
Attributes first, then Directories / Files side by side and Resources - and
the fields it did not name are now grouped by what they hold (Times, Paths &
names, Identity, Values & flags, Other) instead of one long list. Every value
is coloured by its kind, with the same palette the table columns use
(ui/column_colors.py).

The site's look (ui/site_theme.py): one sheet for the whole dialog. The old
version set a stylesheet on every label, so a 400-field row polished 800+
sheets.
"""
import csv
import io
import json

from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtCore import Qt

from styles import CrowEyeStyles

try:
    from ui.site_theme import (apply_site_theme, begin_site_theme, set_role, set_variant, Card,
                               font as site_font,
                               families, MUTED, LINE, BG, CARD, TEXT, LAVENDER)
except Exception:                                         # pragma: no cover
    apply_site_theme = None

try:
    from ui.column_colors import classify_column, COLORS as KIND_COLORS
except Exception:                                         # pragma: no cover
    classify_column = None
    KIND_COLORS = {}

# A value longer than this is shown cut (Copy value / Copy all / Export get it whole).
MAX_SHOWN = 20000

# Fields the column classifier does not know get these cards, in this order.
KIND_SECTIONS = (
    ("Times", ("time", "parsed")),
    ("Paths & names", ("path", "name")),
    ("Identity", ("user", "hash", "id", "net")),
    ("Values & flags", ("value", "flag", "size")),
)


def _text(value):
    """A cell value as text: lists / dicts (Timeline, Database Search) too."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return " | ".join(_text(v) for v in value)
    if isinstance(value, dict):
        try:
            return json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            return str(value)
    return str(value)


# Crow-Eye joins a list into one cell as "a | b | c". A command line can hold a
# pipe too ("cmd /c type x | findstr y"), so a value is shown one entry per
# line only when it carries the spaced separator at least twice, and never for
# a field that holds a command or arguments.
_NOT_LISTS = ("command", "cmd", "argument", "args", "commandline", "command_line",
              "script", "query", "value", "data", "url")


def _is_list(field, text):
    f = str(field).lower()
    if any(k in f for k in _NOT_LISTS):
        return False
    return text.count(" | ") >= 2 or (text.count(" | ") == 1 and "\n" not in text and len(text) < 400
                                     and f.endswith(("s", "times", "list")))


def _list_parts(text):
    return [p.strip() for p in text.split(" | ") if p.strip()]


def _kind(field):
    if classify_column is None:
        return None
    try:
        return classify_column(field)
    except Exception:
        return None


def _extra_qss():
    """The dialog's own pieces on top of the site sheet: value wells coloured
    by kind (one rule per kind, not one sheet per label)."""
    mono = families()[1] if apply_site_theme else "Consolas"
    rules = [
        "QLabel[rdField=\"true\"] { color: %s; font-size: 12px; font-weight: 600; padding: 7px 4px 0 0; }" % MUTED,
        "QLabel[rdValue=\"true\"] { color: %s; background: %s; border: 1px solid %s; border-left: 2px solid %s;"
        " border-radius: 8px; padding: 6px 10px; font-family: '%s'; font-size: 12px; }"
        % ("#E2E8F0", BG, LINE, "rgba(255,255,255,0.14)", mono),
        "QLabel[rdListHead=\"true\"] { color: %s; font-size: 11px; font-weight: 700; padding: 2px 0 4px 2px; }" % MUTED,
        "QWidget#rdSectionHead { background: transparent; }",
        "QWidget#rdSectionHead:hover QLabel#rdSectionTitle { color: %s; }" % TEXT,
        "QLabel#rdSectionTitle { color: %s; font-size: 12px; font-weight: 700; }" % LAVENDER,
        "QLabel#rdChevron { color: %s; font-size: 11px; }" % MUTED,
        "QLabel#rdCount { color: %s; font-size: 11px; }" % MUTED,
        "QWidget#rdIndent { border-left: 1px solid %s; margin-left: 10px; }" % LINE,
        "QLabel#rdChip { color: %s; background: rgba(99,102,241,0.16); border: 1px solid #6366F1;"
        " border-radius: 10px; padding: 2px 10px; font-family: '%s'; font-size: 12px; font-weight: 700; }"
        % (LAVENDER, mono),
        "QFrame#rdHeader { background: %s; border: 1px solid %s; border-radius: 16px; }" % (CARD, LINE),
    ]
    for kind, colour in KIND_COLORS.items():
        rules.append("QLabel[rdValue=\"true\"][kind=\"%s\"] { color: %s; border-left: 2px solid %s; }"
                     % (kind, colour, colour))
    return "\n".join(rules)


class CollapsibleSection(QtWidgets.QFrame):
    """A card with a clickable header (chevron, title, field count) and an
    indented body that folds away. Same API as before: setContentWidget,
    toggle_expanded, is_expanded."""

    def __init__(self, title, parent=None):
        super(CollapsibleSection, self).__init__(parent)
        self.title = title
        self.content_widget = None
        self.is_expanded = True
        self.setProperty("card", True)

        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.setContentsMargins(14, 10, 14, 12)
        self.main_layout.setSpacing(6)

        self.header_widget = QtWidgets.QWidget()
        self.header_widget.setObjectName("rdSectionHead")
        self.header_widget.setCursor(Qt.PointingHandCursor)
        self.header_layout = QtWidgets.QHBoxLayout(self.header_widget)
        self.header_layout.setContentsMargins(0, 0, 0, 0)
        self.header_layout.setSpacing(8)

        self.arrow_label = QtWidgets.QLabel("▼")
        self.arrow_label.setObjectName("rdChevron")
        self.header_layout.addWidget(self.arrow_label)

        self.title_label = QtWidgets.QLabel(title)
        self.title_label.setObjectName("rdSectionTitle")
        if apply_site_theme:
            self.title_label.setFont(site_font("ui", 12, QtGui.QFont.Bold, upper=True, spacing=108))
        self.header_layout.addWidget(self.title_label)

        self.count_label = QtWidgets.QLabel("")
        self.count_label.setObjectName("rdCount")
        self.header_layout.addWidget(self.count_label)
        self.header_layout.addStretch()
        self.main_layout.addWidget(self.header_widget)

        # The body, indented under a hairline (the old dialog's indentation).
        self.content_area = QtWidgets.QWidget()
        self.content_area.setObjectName("rdIndent")
        self.content_area.setAttribute(Qt.WA_StyledBackground, True)
        self.content_layout = QtWidgets.QVBoxLayout(self.content_area)
        self.content_layout.setContentsMargins(14, 2, 0, 0)
        self.main_layout.addWidget(self.content_area)

        self.header_widget.mousePressEvent = self.toggle_expanded

    def setContentWidget(self, widget):
        """Set the content widget for this section."""
        if self.content_layout.count() > 0:
            existing_widget = self.content_layout.itemAt(0).widget()
            if existing_widget:
                existing_widget.setParent(None)
        self.content_widget = widget
        self.content_layout.addWidget(widget)

    def set_count(self, shown, total=None):
        if total is None or total == shown:
            self.count_label.setText("%d" % shown)
        else:
            self.count_label.setText("%d of %d" % (shown, total))

    def toggle_expanded(self, event=None):
        """Toggle the expanded state of the section."""
        self.is_expanded = not self.is_expanded
        self.arrow_label.setText("▼" if self.is_expanded else "▶")
        self.content_area.setVisible(self.is_expanded)
        self.updateGeometry()


class _ValueLabel(QtWidgets.QLabel):
    """A value: selectable, wrapped, coloured by kind, with a copy menu."""

    def __init__(self, field, full_text, shown_text, kind, parent=None):
        super().__init__(shown_text, parent)
        self.field, self.full_text = field, full_text
        self.setProperty("rdValue", True)
        if kind:
            self.setProperty("kind", kind)
        # Wrap only what can need it: a wrapped label makes the layout ask
        # height-for-width through every nested level, and most values are
        # one short line (150 fields: 0.25 s -> see the round-17 notes).
        self.setWordWrap(len(shown_text) > 70 or "\n" in shown_text)
        self.setTextFormat(Qt.PlainText)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        self.setMinimumWidth(240)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

    def _menu(self, pos):
        menu = QtWidgets.QMenu(self)
        menu.addAction("Copy value", lambda: QtWidgets.QApplication.clipboard().setText(self.full_text))
        menu.addAction('Copy "%s: value"' % self.field,
                       lambda: QtWidgets.QApplication.clipboard().setText(
                           "%s: %s" % (self.field, self.full_text)))
        if self.hasSelectedText():
            menu.addAction("Copy selection",
                           lambda: QtWidgets.QApplication.clipboard().setText(self.selectedText()))
        menu.exec_(self.mapToGlobal(pos))


class RowDetailDialog(QtWidgets.QDialog):
    """
    Dialog to display detailed information from a table row.
    Allows multiple instances to be opened for comparison.
    """

    # Keep track of open dialogs to manage positioning
    open_dialogs = []

    def __init__(self, data, title, row_name="Unknown", row_number=0, parent=None):
        """
        Args:
            data (dict): row data (header or column: value)
            title (str): the table's name
            row_name (str): the row's identifier
            row_number (int): row number
            parent: parent widget
        """
        # A caller that passed (parent, title, data) - the unused main-window
        # handler did - still gets its data shown.
        if not isinstance(data, dict) and isinstance(row_name, dict):
            data, row_name = row_name, "Unknown"
        super(RowDetailDialog, self).__init__(parent)
        RowDetailDialog.open_dialogs.append(self)

        self.row_data = dict(data or {}) if isinstance(data, dict) else {}
        self.table_name = title
        self.row_name = row_name
        try:
            self.row_number = int(row_number or 0)
        except (TypeError, ValueError):
            self.row_number = 0
        self.is_maximized = False
        self._rows = []            # [{field, text, widgets, section, empty}]
        self._sections = []

        # The sheet first, so every label is polished once, under it.
        extra = _extra_qss() if apply_site_theme else ""
        if apply_site_theme:
            begin_site_theme(self, extra)
        self._setup_ui()
        self._position_dialog()
        if self.row_data:
            self._populate_grid(self.row_data)
        self._apply_filter()
        if apply_site_theme:
            apply_site_theme(self, extra=extra)

    # ------------------------------------------------------------------ build
    def _setup_ui(self):
        """Set up the dialog UI components."""
        self.setWindowTitle(f"Row Details - {self.table_name}")
        self.setMinimumSize(700, 500)
        # Maximize AND minimize. Without the minimize hint the window cannot be
        # sent to the taskbar at all, so its title never appears there - which
        # is the whole point of having one.
        self.setWindowFlags(Qt.Window | Qt.WindowMinimizeButtonHint
                            | Qt.WindowMaximizeButtonHint | Qt.WindowCloseButtonHint)
        # Owned windows get no taskbar button on Windows, whatever their title
        # says - so a minimized Crow-Eye window had nowhere to show its name.
        # See CrowEyeStyles.give_window_a_taskbar_button for the measurements.
        try:
            from styles import CrowEyeStyles as _CES
            _CES.give_window_a_taskbar_button(self)
        except Exception:
            pass

        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 12)
        main_layout.setSpacing(12)

        # Header card: table, row, number - then the filter row.
        header = Card() if apply_site_theme else QtWidgets.QFrame()
        header.setObjectName("rdHeader")
        header.RADIUS = 16.0
        hl = QtWidgets.QVBoxLayout(header)
        hl.setContentsMargins(18, 14, 18, 14)
        hl.setSpacing(4)
        top = QtWidgets.QHBoxLayout()
        top.setSpacing(10)
        title_label = QtWidgets.QLabel(str(self.table_name))
        if apply_site_theme:
            set_role(title_label, "title")
            title_label.setFont(site_font("ui", 22, QtGui.QFont.ExtraBold, upper=True, spacing=104))
        top.addWidget(title_label)
        if self.row_number > 0:
            chip = QtWidgets.QLabel("#%d" % self.row_number)
            chip.setObjectName("rdChip")
            top.addWidget(chip, 0, Qt.AlignVCenter)
        top.addStretch()
        hl.addLayout(top)
        name = str(self.row_name or "")
        if name and name.lower() not in ("unknown", "none", "n/a"):
            sub = QtWidgets.QLabel(name)
            sub.setWordWrap(True)
            sub.setTextInteractionFlags(Qt.TextSelectableByMouse)
            if apply_site_theme:
                set_role(sub, "subtitle")
            hl.addWidget(sub)

        tools = QtWidgets.QHBoxLayout()
        tools.setContentsMargins(0, 8, 0, 0)
        tools.setSpacing(10)
        self.filter_edit = QtWidgets.QLineEdit()
        self.filter_edit.setPlaceholderText("Filter fields and values...")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._apply_filter)
        tools.addWidget(self.filter_edit, 1)
        self.show_empty_check = QtWidgets.QCheckBox("Show empty fields")
        self.show_empty_check.toggled.connect(self._apply_filter)
        tools.addWidget(self.show_empty_check)
        self.count_label = QtWidgets.QLabel("")
        if apply_site_theme:
            set_role(self.count_label, "mono")
        tools.addWidget(self.count_label)
        hl.addLayout(tools)
        main_layout.addWidget(header)

        scroll_area = QtWidgets.QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.content_widget = QtWidgets.QWidget()
        self.content_layout = QtWidgets.QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(0, 0, 4, 0)
        self.content_layout.setSpacing(10)
        scroll_area.setWidget(self.content_widget)
        main_layout.addWidget(scroll_area, 1)
        self.empty_note = QtWidgets.QLabel("No field matches the filter.")
        if apply_site_theme:
            set_role(self.empty_note, "muted")
        self.empty_note.hide()
        main_layout.addWidget(self.empty_note)

        button_layout = QtWidgets.QHBoxLayout()
        button_layout.setSpacing(10)
        copy_button = QtWidgets.QPushButton("Copy all")
        copy_button.setToolTip("Every field of this row, as 'field: value' lines")
        copy_button.clicked.connect(self._copy_to_clipboard)
        export_button = QtWidgets.QPushButton("Export")
        export_button.setToolTip("Save this row as TXT, CSV or JSON")
        export_button.clicked.connect(self._export_data)
        close_button = QtWidgets.QPushButton("Close")
        close_button.clicked.connect(self.close)
        for b, v in ((copy_button, "ghost"), (export_button, "ghost"), (close_button, "ghost")):
            b.setMinimumHeight(32)
            if apply_site_theme:
                set_variant(b, v)
            else:
                b.setStyleSheet(CrowEyeStyles.BUTTON_STYLE)
        button_layout.addWidget(copy_button)
        button_layout.addWidget(export_button)
        button_layout.addStretch()
        button_layout.addWidget(close_button)
        main_layout.addLayout(button_layout)

    # ------------------------------------------------------------- populate
    def _value_label(self, field, text, split_lists=False):
        """A value well. ``split_lists``: a 'a | b | c' value shows one entry
        per line. A value past MAX_SHOWN is cut on screen only - Copy value,
        Copy all and Export always carry all of it."""
        if not text.strip():
            shown = "(empty)"
        else:
            shown = "\n".join(_list_parts(text)) if (split_lists and _is_list(field, text)) else text
            if len(shown) > MAX_SHOWN:
                shown = shown[:MAX_SHOWN] + "\n... (%d more characters - Copy value gets all of it)" % (
                    len(shown) - MAX_SHOWN)
        return _ValueLabel(field, text, shown, _kind(field))

    def _field_grid(self, fields, section):
        """name | value rows for ``fields`` (indented under the section)."""
        body = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(body)
        grid.setContentsMargins(0, 4, 0, 2)
        grid.setColumnStretch(1, 1)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(6)
        for r, field in enumerate(fields):
            text = _text(self.row_data.get(field))
            name_label = QtWidgets.QLabel(str(field))
            name_label.setProperty("rdField", True)
            name_label.setAlignment(Qt.AlignRight | Qt.AlignTop)
            value_label = self._value_label(field, text, split_lists=True)
            grid.addWidget(name_label, r, 0)
            grid.addWidget(value_label, r, 1)
            self._rows.append({"field": str(field), "text": text, "widgets": (name_label, value_label),
                               "section": section, "empty": not text.strip()})
        return body

    def _list_column(self, field, items, section):
        """A heading and one well per entry (Directories / Files / Resources)."""
        box = QtWidgets.QVBoxLayout()
        box.setSpacing(5)
        head = QtWidgets.QLabel("%s (%d)" % (field, len(items)))
        head.setProperty("rdListHead", True)
        if apply_site_theme:
            head.setFont(site_font("ui", 11, QtGui.QFont.Bold, upper=True, spacing=108))
        box.addWidget(head)
        widgets = [head]
        for entry in items:
            lab = self._value_label(field, entry)
            box.addWidget(lab)
            widgets.append(lab)
        box.addStretch()
        self._rows.append({"field": field, "text": " | ".join(items), "widgets": tuple(widgets),
                           "section": section, "empty": False})
        return box

    def _populate_grid(self, row_data):
        """The row's fields, grouped: the named sections first, the list
        fields, then every other field in a card for its kind."""
        categories = {
            "File Info": ["Filename", "Executable Name", "Hash"],
            "Timestamps": ["Run Count", "Last Executed", "Run Times"],
            "Attributes": [
                "apptype", "artifact", "data_flags", "volume_label", "entry_number",
                "network_device_name", "network_share_flags", "network_share_name",
                "network_share_name_uni", "file_permissions", "num_hard_links", "inode_number", "owner_uid"
            ],
        }
        processed = set()
        for category_name, fields in categories.items():
            present = [f for f in fields if f in row_data]
            if not present:
                continue
            section = self._create_collapsible_section(category_name)
            section.setContentWidget(self._field_grid(present, section))
            self.content_layout.addWidget(section)
            processed.update(present)

        def split(field):
            return [p.strip() for p in _text(row_data.get(field)).split("|") if p.strip()]

        dirs, files = split("Directories"), split("Files")
        if dirs or files:
            section = self._create_collapsible_section("Paths")
            body = QtWidgets.QWidget()
            side = QtWidgets.QHBoxLayout(body)
            side.setContentsMargins(0, 4, 0, 2)
            side.setSpacing(16)
            if dirs:
                side.addLayout(self._list_column("Directories", dirs, section), 1)
            if files:
                side.addLayout(self._list_column("Files", files, section), 1)
            section.setContentWidget(body)
            self.content_layout.addWidget(section)
        # Present but empty: an ordinary field row, so "Show empty fields" can show it.
        processed.update(f for f, items in (("Directories", dirs), ("Files", files)) if items)

        resources = split("Resources")
        if resources:
            section = self._create_collapsible_section("Resources")
            body = QtWidgets.QWidget()
            col = self._list_column("Resources", resources, section)
            col.setContentsMargins(0, 4, 0, 2)
            body.setLayout(col)
            section.setContentWidget(body)
            self.content_layout.addWidget(section)
        if resources:
            processed.add("Resources")

        # Everything else, in a card for what it holds; field order kept.
        remaining = [f for f in row_data.keys() if f not in processed]
        buckets = {name: [] for name, _k in KIND_SECTIONS}
        buckets["Other"] = []
        for f in remaining:
            k = _kind(f)
            target = "Other"
            for name, kinds in KIND_SECTIONS:
                if k in kinds:
                    target = name
                    break
            buckets[target].append(f)
        for name in [n for n, _k in KIND_SECTIONS] + ["Other"]:
            fields = buckets[name]
            if not fields:
                continue
            section = self._create_collapsible_section(name)
            section.setContentWidget(self._field_grid(fields, section))
            self.content_layout.addWidget(section)
        self.content_layout.addStretch()

    def _create_collapsible_section(self, title):
        """Create a collapsible section with the given title."""
        section = CollapsibleSection(title)
        self._sections.append(section)
        return section

    # --------------------------------------------------------------- filter
    def _apply_filter(self, *_):
        """Hide fields that do not match the filter (name or value), and the
        empty ones unless asked; a section with nothing left hides too."""
        needle = self.filter_edit.text().strip().lower() if hasattr(self, "filter_edit") else ""
        show_empty = self.show_empty_check.isChecked() if hasattr(self, "show_empty_check") else False
        shown_per = {}
        total_per = {}
        shown = 0
        for row in self._rows:
            ok = (show_empty or not row["empty"]) and (
                not needle or needle in row["field"].lower() or needle in row["text"].lower())
            if row.get("shown", True) != ok:
                # Only what changes: setVisible on 800 labels that already
                # had the right state cost 0.2 s on a 400-field row.
                for w in row["widgets"]:
                    w.setVisible(ok)
                row["shown"] = ok
            sec = row["section"]
            total_per[sec] = total_per.get(sec, 0) + (0 if row["empty"] and not show_empty else 1)
            if ok:
                shown_per[sec] = shown_per.get(sec, 0) + 1
                shown += 1
        for sec in self._sections:
            n = shown_per.get(sec, 0)
            if sec.isHidden() == (n > 0):      # only on a change (see above)
                sec.setVisible(n > 0)
            sec.set_count(n, total_per.get(sec, 0) if needle else None)
        filled = sum(1 for r in self._rows if not r["empty"])
        if hasattr(self, "count_label"):
            self.count_label.setText("%d of %d fields" % (shown, len(self._rows)) if needle or show_empty
                                     else "%d fields" % filled)
        if hasattr(self, "empty_note"):
            want = bool(self._rows) and shown == 0
            if self.empty_note.isHidden() == want:
                self.empty_note.setVisible(want)

    # ----------------------------------------------------------- positions
    def _position_dialog(self):
        """Position the dialog based on open instances."""
        screen = QtWidgets.QApplication.primaryScreen().availableGeometry()
        width = 900
        height = 680
        margin = 40
        num_dialogs = len(RowDetailDialog.open_dialogs)
        x = screen.width() - (width + margin) if num_dialogs % 2 == 1 else margin
        y = margin + (num_dialogs // 2) * (height // 2)
        self.setGeometry(x, y, width, min(height, screen.height() - 2 * margin))

    # ------------------------------------------------------- copy / export
    def _pairs(self):
        """(field, value) for every field of the row, in its order. Read from
        the data itself: the old copy walked the layout for grids that were
        nested one level deeper, and copied nothing."""
        return [(str(k), _text(v)) for k, v in self.row_data.items()]

    def _copy_to_clipboard(self):
        """Copy row data to clipboard in a human-readable format."""
        text = "\n".join("%s: %s" % (k, v) for k, v in self._pairs())
        QtWidgets.QApplication.clipboard().setText(text)
        QtWidgets.QMessageBox.information(
            self, "Copied", "%d field(s) of this row were copied to the clipboard." % len(self._pairs()))

    def _export_data(self):
        """Export row data to a TXT, CSV or JSON file."""
        try:
            file_path, chosen = QtWidgets.QFileDialog.getSaveFileName(
                self, "Export Row Details", "row_details.txt",
                "Text Files (*.txt);;CSV Files (*.csv);;JSON Files (*.json)")
            if not file_path:
                return
            self._write_export(file_path, chosen)
            QtWidgets.QMessageBox.information(
                self, "Export Successful", f"Row details have been exported to {file_path}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Export Failed", f"Failed to export data: {str(e)}")

    def _write_export(self, file_path, chosen=""):
        pairs = self._pairs()
        lower = file_path.lower()
        if lower.endswith(".csv") or ("CSV" in (chosen or "") and not lower.endswith((".txt", ".json"))):
            with open(file_path, "w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(["Name", "Value"])
                w.writerows(pairs)
        elif lower.endswith(".json") or ("JSON" in (chosen or "") and not lower.endswith((".txt", ".csv"))):
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump({"table": str(self.table_name), "row": str(self.row_name),
                           "row_number": self.row_number, "fields": dict(pairs)},
                          f, indent=2, ensure_ascii=False)
        else:
            with open(file_path, "w", encoding="utf-8") as f:
                for name, value in pairs:
                    f.write(f"{name}: {value}\n")

    def closeEvent(self, event):
        """Handle dialog close event."""
        if self in RowDetailDialog.open_dialogs:
            RowDetailDialog.open_dialogs.remove(self)
        event.accept()
