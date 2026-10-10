"""One colour per kind of standard column, in every artifact table.

The same few kinds of value appear in most of Crow-Eye's ~215 tables: when
the parser ran, event times, paths, hashes, users and SIDs, sizes and names.
Each kind gets a tint of its own (the website's indigo / cyan family, all
readable on the #11151c / #141923 rows), so the eye finds them without
reading the headers:

    times      #67E8F9   created / modified / accessed / last written ...
    paths      #A5B4FC   key path, file path, URL, working directory ...
    hashes     #C4B5FD   SHA-1, SHA-256, MD5, AmCache file_id ...
    users      #F9A8D4   user name, SID, owner, RID ...
    sizes      #FDBA74   size, file size, bytes ...
    names      #F8FAFC   name, file name, display name ... (bold)
    parsed     #94A3B8   parsed_at - parser bookkeeping, a quiet slate
    ids        #FDE68A   id, record number, entry number, USN, sequence, offset ...
    values     #86EFAC   registry value / data, decoded data, raw blobs ...
    flags      #FCA5A5   is_* / has_*, flags, state, status, enabled ...
    network    #5EEAD4   IP, MAC, host, gateway, port; devices: vendor, model,
                         serial number, product, hardware id ...

The first seven win over the last four: `file_id` is a hash, `user_id` a
user, `device_name` a name, `bytes_sent` a size.

Why a delegate, not item colours: the table stylesheet sets `color:` on
`::item`, and a stylesheet colour beats QTableWidgetItem.setForeground - an
item colour is simply never drawn. The delegate lets the style paint the cell
(background, stripe, hover, selection) with no text, then draws the text in
the column's colour itself.

Which kind a column is comes from its name: the database column a header
carries in Qt.UserRole (registry tabs, virtual tables), or else the header
text, normalised ("Parsed At" -> parsed_at). Matching is on whole tokens, with
exclusions first: `times_used`, `time_zone_name`, `foreground_cycle_time`,
`*_timeline`, `focus_time` (a duration) and the like are not timestamps.
"""

import re

from PyQt5 import QtCore, QtGui, QtWidgets

try:
    from styles import Colors as _C
    COLORS = {"time": _C.COL_TIME, "path": _C.COL_PATH, "hash": _C.COL_HASH,
              "user": _C.COL_USER, "size": _C.COL_SIZE, "name": _C.COL_NAME,
              "parsed": _C.COL_PARSED, "id": _C.COL_ID, "value": _C.COL_VALUE,
              "flag": _C.COL_FLAG, "net": _C.COL_NET}
except Exception:                                        # standalone use
    COLORS = {"time": "#67E8F9", "path": "#A5B4FC", "hash": "#C4B5FD",
              "user": "#F9A8D4", "size": "#FDBA74", "name": "#F8FAFC",
              "parsed": "#94A3B8", "id": "#FDE68A", "value": "#86EFAC",
              "flag": "#FCA5A5", "net": "#5EEAD4"}

GROUPS = ("parsed", "time", "path", "hash", "user", "size", "name",
          "id", "value", "flag", "net")

# parser bookkeeping: the canonical column and its read-only legacy aliases
# (utils/parse_time_column.py). `timestamp` is NOT here: in SRUM and the USN
# journal it is the event time, so it is coloured as a time.
_PARSED = {"parsed_at", "parsed_timestamp", "parse_timestamp", "inserted_at",
           "parse_time", "parsed_time", "parsed_on"}

# Names the token rules would get wrong, decided by hand (checked first).
_INCLUDE = {"timeline_end": "time", "driver_time_stamp": "time",
            "last_modified_readable": "time", "registered_owner": "user",
            "raw_size": "size", "tracker_net_bios": "net"}

# Never coloured: counters, flags, durations, time-zone fields, SRUM per-
# second series and raw blobs that merely contain a matching word.
_EXCLUDE = {
    "time_basis", "times_used", "run_times", "time_zone_name", "active_time_bias",
    "face_time", "focus_time", "connected_time", "in_focus_time", "watch_time_seconds",
    "scheduled_install_time", "parsing_duration_seconds", "position_seconds",
    "profile", "username_element", "utc_offset",
    "last_known_usn", "last_four", "last_result", "last_activated_version",
    "daylight_start_rule", "standard_start_rule", "name_kind", "name_kind_raw",
    "name_type", "name_type_label", "name_on_card",
}
_EXCLUDE_TOKENS = {"count", "counter", "timeline", "cycle", "bias", "zone", "duration",
                   "raw", "b64", "encrypted", "flags", "is", "has"}

_TIME_LAST = {"time", "timestamp", "date", "utc", "written", "write", "mtime",
              "modified", "accessed", "created", "updated"}
_TIME_FIRST = {"date", "time"}
_TIME_ONAT_FIRST = {"created", "modified", "accessed", "changed", "deleted",
                    "disabled", "installed", "updated", "reorganized", "renamed"}
_LASTFIRST_END = {"modified", "accessed", "updated", "seen", "run", "used", "executed",
                  "execution", "logon", "visit", "connected", "removed", "completed",
                  "set", "installed", "start", "stop", "password", "interaction",
                  "opened", "write", "written"}
_TIME_EXACT = {"created", "modified", "accessed", "updated", "expiry", "mtime",
               "password_last_set", "account_expires", "lease_expires", "lease_obtained",
               "install_date", "installation_date", "changed_after", "changed_before",
               "timestamp", "date"}

_PATH_LAST = {"path", "paths", "dir", "directory", "folder", "url", "uri", "location",
              "cwd"}

_HASH_TOKENS = {"sha1", "sha256", "sha512", "md5", "imphash"}
_HASH_EXACT = {"hash", "file_id"}

_USER_EXACT = {"user", "user_name", "username", "user_id", "sid", "owner", "owner_id",
               "owner_uid", "owner_gid", "security_id", "rid", "account", "account_name",
               "full_name", "member_name", "examiner", "username_value",
               "username_hint", "logon_user"}

_SIZE_EXACT = {"size", "file_size", "filesize", "content_length", "total_bytes",
               "bytes_sent", "bytes_received", "received_bytes", "changed_bytes"}

_NAME_LAST = {"name", "filename"}

# -- the second tier: tested only when none of the seven above applies ------
# Counters, durations, time-zone fields, SRUM per-second series and secrets
# stay plain in this tier too.
_NEW_VETO = {"count", "counter", "timeline", "cycle", "bias", "zone", "duration",
             "b64", "encrypted", "seconds"}
_FLAG_LAST = {"flags", "flag", "state", "status", "enabled", "disabled", "exists",
              "signed", "managed", "deleted", "active", "persistent", "verified",
              "partial", "valid", "blacklisted", "packaged", "replayed", "resident",
              "occupied", "dirty"}
_VALUE_EXACT = {"value", "data", "default_value", "row_data", "value_raw", "raw",
                "value_data", "property_value", "setting_value", "value_before",
                "trailing_value", "decoded", "raw_entry", "raw_hex", "contents"}
_NET_TOKENS = {"ip", "mac", "host", "hostname", "gateway", "dns", "port", "subnet",
               "ssid", "dhcp", "netbios", "vendor", "manufacturer", "model", "serial",
               "hwid", "hwids", "device", "enumerator", "adapter", "interface",
               "endpoint", "network"}
_NET_EXACT = {"product", "product_id", "product_version", "vendor_id", "interface_luid",
              "server"}
_ID_LAST = {"id", "ids", "number", "seq", "sequence", "usn", "frn", "index", "offset",
            "luid"}
_ID_EXACT = {"seq", "usn", "inode", "record", "parent_record", "slot", "node_slot"}


def normalise(name):
    """'Parsed At' / 'EventTimestampUTC' / 'FileSize' -> parsed_at /
    event_timestamp_utc / file_size."""
    s = str(name or "").strip()
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", s)
    s = re.sub(r"[^0-9A-Za-z]+", "_", s).strip("_").lower()
    # A normalised acronym run ("s_h_a1") never happens: SHA1 has no
    # lower->upper boundary, so it stays "sha1".
    return s


def classify_column(name):
    """The group of a column name ("time", "path", ...), or None."""
    n = normalise(name)
    if not n:
        return None
    if n in _PARSED or n.startswith("parsed_"):
        return "parsed"
    if n in _INCLUDE:
        return _INCLUDE[n]
    if n in _EXCLUDE:
        return None
    t = n.split("_")
    if _EXCLUDE_TOKENS.intersection(t) or t[-1] in ("s", "ms", "id", "ids", "type",
                                                  "kind", "state", "status", "version"):
        # ...except the few that ARE what they look like
        if n not in _USER_EXACT and n not in _HASH_EXACT:
            return _second_tier(n, t)
    if n in _USER_EXACT or t[-1] == "sid" or (t[0] == "owner" and len(t) > 1) \
            or (t[0] == "username" and len(t) == 2):
        return "user"
    if n in _HASH_EXACT or _HASH_TOKENS.intersection(t) or t[-1] == "hash":
        return "hash"
    if n in _SIZE_EXACT or t[-1] == "size" or t[0] == "size" or "bytes" in t:
        return "size"
    if n in _TIME_EXACT or t[-1] in _TIME_LAST or t[0] in _TIME_FIRST \
            or (t[-1] in ("on", "at") and t[0] in _TIME_ONAT_FIRST) \
            or (t[0] in ("last", "first") and t[-1] in _LASTFIRST_END):
        return "time"
    if t[-1] in _PATH_LAST:
        return "path"
    if t[-1] in _NAME_LAST:
        return "name"
    return _second_tier(n, t)


def _second_tier(n, t):
    """ids, values, flags and network/device columns."""
    if _NEW_VETO.intersection(t) or t[-1] in ("s", "ms", "timeline"):
        return None
    if t[0] in ("is", "has") or t[-1] in _FLAG_LAST or n == "in_use":
        return "flag"
    if n in _VALUE_EXACT or t[-1] in ("decoded", "raw"):
        return "value"
    if (n in _NET_EXACT or _NET_TOKENS.intersection(t)) and "orientation" not in t:
        return "net"
    if n in _ID_EXACT or t[-1] in _ID_LAST:
        if n.endswith("version_number"):
            return None
        return "id"
    return None


def column_key(view, section):
    """The column name behind a header section: the database name the header
    carries in Qt.UserRole when there is one, else the header's text."""
    model = view.model()
    if model is None:
        return ""
    for role in (QtCore.Qt.UserRole, QtCore.Qt.DisplayRole):
        try:
            value = model.headerData(section, QtCore.Qt.Horizontal, role)
        except Exception:
            value = None
        if value:
            return str(value)
    return ""


class ColumnColorDelegate(QtWidgets.QStyledItemDelegate):
    """Draws each standard column's text in its group's colour.

    Columns that match no group are painted exactly as before (the base
    delegate), so a table only changes where a colour applies.
    """

    def __init__(self, view):
        super().__init__(view)
        self._view = view
        self._groups = {}
        self._model = None
        self._watch(view.model())

    # -- which column is which --------------------------------------------
    def _watch(self, model):
        if model is self._model or model is None:
            return
        self._model = model
        for sig in (model.headerDataChanged, model.modelReset, model.columnsInserted,
                    model.columnsRemoved, model.columnsMoved, model.layoutChanged):
            try:
                sig.connect(self.invalidate)
            except Exception:
                pass

    def invalidate(self, *args):
        self._groups.clear()

    def group(self, column):
        if self._view.model() is not self._model:
            self._groups.clear()
            self._watch(self._view.model())
        if column not in self._groups:
            self._groups[column] = classify_column(column_key(self._view, column))
        return self._groups[column]

    # -- painting -----------------------------------------------------------
    def paint(self, painter, option, index):
        group = self.group(index.column())
        if group is None:
            return super().paint(painter, option, index)
        opt = QtWidgets.QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text = opt.text
        if not text:
            return super().paint(painter, option, index)
        widget = opt.widget
        style = widget.style() if widget is not None else QtWidgets.QApplication.style()
        opt.text = ""
        style.drawControl(QtWidgets.QStyle.CE_ItemViewItem, opt, painter, widget)

        rect = style.subElementRect(QtWidgets.QStyle.SE_ItemViewItemText, opt, widget)
        font = QtGui.QFont(opt.font)
        if group == "name":
            font.setBold(True)
        if opt.state & QtWidgets.QStyle.State_Selected:
            colour = QtGui.QColor("#FFFFFF")
        else:
            colour = QtGui.QColor(COLORS[group])
        painter.save()
        painter.setFont(font)
        painter.setPen(colour)
        fm = QtGui.QFontMetrics(font)
        margin = style.pixelMetric(QtWidgets.QStyle.PM_FocusFrameHMargin, None, widget) + 1
        rect = rect.adjusted(margin, 0, -margin, 0)
        line = text.replace("\r", " ").replace("\n", " ")
        shown = fm.elidedText(line, opt.textElideMode, rect.width())
        align = opt.displayAlignment or (QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        painter.drawText(rect, int(align), shown)
        painter.restore()


def install(view):
    """Give `view` (a QTableWidget or QTableView) the column colours.
    Idempotent; returns the delegate."""
    if view is None:
        return None
    current = view.itemDelegate()
    if isinstance(current, ColumnColorDelegate):
        current.invalidate()
        return current
    delegate = ColumnColorDelegate(view)
    view.setItemDelegate(delegate)
    return delegate
