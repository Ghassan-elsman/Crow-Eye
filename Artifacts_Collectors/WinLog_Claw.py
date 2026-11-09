try:
    import win32evtlog
except ImportError:
    win32evtlog = None
import json
import re
import sqlite3
import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

# Add the parent directory to sys.path to import utils
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.time_utils import ensure_utc, format_timestamp, format_forensic_timestamp, get_current_utc
from utils.dedupe_insert import Tally, ensure_identity_index, insert_new

# Column order of each table's rows, RecordNumber last. The event record
# number (EventRecordID) is what tells two events apart: without it, the
# Security log held 34,694 rows of which only 11,787 were distinct by content
# - real, separate events that look identical - and a re-parse could not tell
# a new event from one already stored.
EVENT_TABLE_COLUMNS = {
    "SystemLogs": ["EventID", "Source", "EventType", "Category", "EventTimestampUTC",
                   "ComputerName", "User", "Keywords", "EventDescription", "RecordNumber"],
    "ApplicationLogs": ["EventID", "Source", "EventType", "Category", "EventTimestampUTC",
                        "ComputerName", "User", "Keywords", "EventDescription", "RecordNumber"],
    "SecurityLogs": ["EventID", "Source", "EventType", "Category", "EventTimestampUTC",
                     "ComputerName", "User", "Keywords", "TaskCategory", "EventDescription",
                     "RecordNumber"],
}
# Identity of an event: its record number, time and provider (a cleared log
# restarts its numbering, so the number alone is not enough).
EVENT_IDENTITY = ["RecordNumber", "EventTimestampUTC", "Source", "EventID"]

# ------------------------------------------------------- device evidence --
# What a storage device leaves in two channels the classic EventLog API cannot
# open (Sentinel 12.20, decision 162). The registry says a device was seen;
# these say when it arrived and left, and what it was:
#   Partition/Diagnostic 1006 - written when a disk arrives (its model,
#     serial, bus, capacity, partition table) and again when it leaves (the
#     same disk with Capacity 0 and no partitions). On by default.
#   DriverFrameworks-UserMode/Operational 2003 (the UMDF host asked to load
#     drivers for a device) and 2100 (a PnP or power request to it, the
#     removal among them). The channel is OFF by default on Windows 10 and
#     11: on most machines it holds nothing, and an empty table says so.
# One table per channel, named for the channel; the event's own field names
# for its columns, and every field of the event in EventData (JSON).
DEVICE_CHANNELS = {
    "Microsoft-Windows-Partition/Diagnostic": ("partition_diagnostic", (1006,)),
    "Microsoft-Windows-DriverFrameworks-UserMode/Operational": ("driver_frameworks_usermode",
                                                                (2003, 2100)),
}
DEVICE_TABLE_COLUMNS = {
    "partition_diagnostic": [
        "EventID", "EventTimestampUTC", "ComputerName", "RecordNumber", "DiskNumber",
        "BusType", "Manufacturer", "Model", "Revision", "SerialNumber", "ParentId",
        "Location", "Capacity", "PartitionStyle", "PartitionCount", "DiskId", "AdapterId",
        "RegistryId", "UserRemovalPolicy", "EventData"],
    "driver_frameworks_usermode": [
        "EventID", "EventTimestampUTC", "ComputerName", "User", "RecordNumber", "InstanceId",
        "SerialNumber", "LifetimeId", "MajorCode", "MinorCode", "Status", "EventData"],
}
DEVICE_IDENTITY = ["RecordNumber", "EventTimestampUTC", "EventID"]
_EVT_NS = "{http://schemas.microsoft.com/win/2004/08/events/event}"


def prepare_event_tables(conn):
    """Keep what earlier runs stored, and get the tables ready for this one.

    The tables used to be DROPPED on every parse: an event that had since
    rolled out of the live log was gone from the case as well. Now an older
    case gains the RecordNumber column, the identity is indexed, and a re-parse
    adds only events not stored yet. Returns {table: True when it holds rows
    from before RecordNumber existed}.
    """
    legacy = {}
    for table in ("SystemLogs", "ApplicationLogs", "SecurityLogs"):
        cols = {r[1] for r in conn.execute('PRAGMA table_info("%s")' % table)}
        if "RecordNumber" not in cols:
            conn.execute('ALTER TABLE "%s" ADD COLUMN RecordNumber INTEGER' % table)
        ensure_identity_index(conn, table, ["RecordNumber", "EventTimestampUTC"])
        legacy[table] = conn.execute(
            'SELECT 1 FROM "%s" WHERE RecordNumber IS NULL LIMIT 1' % table).fetchone() is not None
    conn.commit()
    return legacy


def _drop_stored_under_alias(conn, table, cols, rows, aliases, tally):
    """The rows not already stored under the other name of their provider.

    One provider has two names: the classic EventLog API (the live parse)
    reports its event source name ('DCOM', 'Software Protection Platform
    Service'), an .evtx read offline its provider name
    ('Microsoft-Windows-DistributedCOM', 'Microsoft-Windows-Security-SPP').
    Source is part of the identity, so the same event parsed live and then
    from Crow-Claw's collected .evtx (or the other way round) was stored a
    second time - 74 of 300 System and 202 of 1,341 Application events of a
    two-day export. ``aliases`` maps a row's Source to the provider's other
    name; an event stored under that name, with the same record number, time
    and ID, is already present. The row keeps the name its own source gives.
    """
    if not aliases or not rows:
        return rows
    i = {c: cols.index(c) for c in EVENT_IDENTITY}
    sql = ('SELECT 1 FROM "%s" WHERE %s LIMIT 1'
           % (table, " AND ".join("%s IS ?" % c for c in EVENT_IDENTITY)))
    keep = []
    for r in rows:
        alt = aliases.get(r[i["Source"]])
        if alt and alt != r[i["Source"]] and conn.execute(sql, tuple(
                alt if c == "Source" else r[i[c]] for c in EVENT_IDENTITY)).fetchone():
            continue
        keep.append(r)
    if tally is not None and len(keep) < len(rows):
        tally.add(table, len(rows) - len(keep), 0)
    return keep


_PROVIDER_NAMES = {}


def provider_name(log_type, source):
    """The provider name behind a classic event source name, from this
    machine's registry (EventLog\\<log>\\<source> ProviderGuid -> WINEVT
    publisher), or None. 'DCOM' -> 'Microsoft-Windows-DistributedCOM'."""
    key = (log_type, source)
    if key not in _PROVIDER_NAMES:
        name = None
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                "SYSTEM\\CurrentControlSet\\Services\\EventLog\\%s\\%s"
                                % (log_type, source)) as k:
                guid = winreg.QueryValueEx(k, "ProviderGuid")[0]
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\WINEVT\\Publishers\\%s"
                                % guid) as k:
                name = winreg.QueryValueEx(k, "")[0] or None
        except (OSError, ImportError, TypeError, ValueError):
            name = None
        _PROVIDER_NAMES[key] = name
    return _PROVIDER_NAMES[key]


def insert_event_rows(conn, table, rows, tally, legacy=False, aliases=None):
    """Insert the events not stored yet; returns the number inserted.

    ``legacy``: the table holds rows from before RecordNumber was recorded.
    Such a row cannot be matched by number, so an event is also skipped when a
    numberless row with the same time, provider, ID and text exists - the
    first re-parse of an older case does not store its events a second time.
    ``aliases``: {Source: the provider's other name} (_drop_stored_under_alias).
    """
    cols = EVENT_TABLE_COLUMNS[table]
    if not rows:
        return 0
    rows = _drop_stored_under_alias(conn, table, cols, rows, aliases, tally)
    if not rows:
        return 0
    if not legacy:
        return insert_new(conn, table, cols, rows, EVENT_IDENTITY, tally)
    content = ["EventTimestampUTC", "Source", "EventID", "Keywords", "EventDescription"]
    idx = {c: cols.index(c) for c in cols}
    sql = ('INSERT INTO "%s" (%s) SELECT %s WHERE NOT EXISTS (SELECT 1 FROM "%s" WHERE %s) '
           'AND NOT EXISTS (SELECT 1 FROM "%s" WHERE RecordNumber IS NULL AND %s)'
           % (table, ", ".join(cols), ", ".join("?" * len(cols)), table,
              " AND ".join("%s IS ?" % c for c in EVENT_IDENTITY), table,
              " AND ".join("%s IS ?" % c for c in content)))
    params = [tuple(r) + tuple(r[idx[c]] for c in EVENT_IDENTITY) + tuple(r[idx[c]] for c in content)
              for r in rows]
    before = conn.total_changes
    conn.executemany(sql, params)
    inserted = conn.total_changes - before
    if tally is not None:
        tally.add(table, len(rows), inserted)
    return inserted

def _local(tag):
    """An element's name without its namespace."""
    return tag.rsplit("}", 1)[-1]


def _event_iso_utc(system_time):
    """'2026-10-27T09:41:25.4198763Z' -> '2026-10-27 09:41:25' (UTC), or None."""
    if not system_time:
        return None
    m = re.match(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})", system_time)
    if not m:
        return None
    try:
        dt = datetime.strptime("%s %s" % m.groups(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return format_forensic_timestamp(dt)
    except ValueError:
        return None


def serial_from_instance_id(instance_id):
    """The serial number a device instance ID carries, or None.

    USBSTOR\\DISK&VEN_x&PROD_y&REV_z\\<serial>&0, USB\\VID_v&PID_p\\<serial>, and
    the '#'-joined form a WPD or software device repeats it in
    (..._??_USBSTOR#DISK&VEN_..#<serial>&0#{guid}). An ID whose second
    character is '&' is one Windows made up for a device with no serial
    (8&5e75b0f&0&000000): not a serial, so None. The trailing '&<n>' is the
    LUN Windows appends, not part of the serial. Any other enumerator (ACPI,
    PCI, ROOT, SWD without USBSTOR) gives None."""
    if not instance_id:
        return None
    text = str(instance_id).strip()
    cand = None
    if "#" in text:
        parts = [p for p in text.split("#") if p]
        for i, p in enumerate(parts[:-1]):
            if p.upper().startswith(("DISK&", "CDROM&", "VID_")):
                cand = parts[i + 1]
                break
    else:
        # Only USB and USB storage instance IDs carry the device's serial in
        # their last part; an ACPI, PCI, ROOT or SWD ID carries a location or
        # a counter there (NPCF, 0000), not a serial.
        segs = text.split("\\")
        if len(segs) >= 3 and segs[0].upper() in ("USB", "USBSTOR"):
            cand = segs[2]
    if not cand or cand.startswith("{") or (len(cand) > 1 and cand[1] == "&"):
        return None
    return re.sub(r"&\d+$", "", cand) or None


def _event_fields(root):
    """Every named value of an event: EventData's <Data Name=...> and
    UserData's elements and attributes (flattened, element names as keys)."""
    out = {}
    for ed in root.iter(_EVT_NS + "EventData"):
        for d in ed:
            name = d.get("Name")
            if name:
                out[name] = d.text if d.text is not None else ""
    for ud in root.iter(_EVT_NS + "UserData"):
        for el in ud.iter():
            if el is ud:
                continue
            key = _local(el.tag)
            for a, v in el.attrib.items():
                out["%s.%s" % (key, _local(a))] = v
            if len(el) == 0 and el.text is not None and el.text.strip():
                out.setdefault(key, el.text.strip())
    return out


_HEX = re.compile(r"^[0-9A-Fa-f]*$")


def _normalise_fields(f):
    """The values as Windows renders them, whichever reader produced them.

    The live read (EvtRender) and an .evtx read offline (python-evtx) render
    two types differently: a boolean is 'true' live and 'True' offline, and a
    binary field (Mbr, PartitionTable, StorageId) is hex live and base64
    offline. Measured on the same 323 Partition/Diagnostic events read both
    ways. A field is binary when the event also carries its length, as
    <Name>Bytes or <Name>Size; its value is kept as upper-case hex."""
    import base64
    import binascii
    out = {}
    for name, value in f.items():
        if value in ("True", "False"):
            value = value.lower()
        else:
            size = f.get(name + "Bytes", f.get(name + "Size"))
            n = _int(size) if size is not None else None
            if n is not None and value:
                if _HEX.match(value) and len(value) == 2 * n:
                    value = value.upper()
                else:
                    try:
                        blob = base64.b64decode(value, validate=True)
                        if len(blob) == n:
                            value = binascii.hexlify(blob).decode("ascii").upper()
                    except (binascii.Error, ValueError):
                        pass
        out[name] = value
    return out


def _int(value):
    try:
        return int(str(value).strip(), 0)
    except (TypeError, ValueError):
        return None


def device_event_row(root):
    """(table, row) for an event of a device channel, or None. ``root`` is
    the event's XML (live: EvtRender; offline: python-evtx) - one function
    for both, so the two paths cannot read a field differently."""
    system = root.find(_EVT_NS + "System")
    if system is None:
        return None
    channel = (system.findtext(_EVT_NS + "Channel") or "").strip()
    spec = DEVICE_CHANNELS.get(channel)
    if spec is None:
        return None
    table, ids = spec
    event_id = _int(system.findtext(_EVT_NS + "EventID"))
    if event_id not in ids:
        return None
    tc = system.find(_EVT_NS + "TimeCreated")
    ts = _event_iso_utc(tc.get("SystemTime") if tc is not None else None)
    computer = system.findtext(_EVT_NS + "Computer")
    record = _int(system.findtext(_EVT_NS + "EventRecordID"))
    sec = system.find(_EVT_NS + "Security")
    user = sec.get("UserID") if sec is not None else None
    f = _normalise_fields(_event_fields(root))
    data = json.dumps(f, sort_keys=True)
    if table == "partition_diagnostic":
        row = (event_id, ts, computer, record, _int(f.get("DiskNumber")), _int(f.get("BusType")),
               f.get("Manufacturer"), f.get("Model"), f.get("Revision"), f.get("SerialNumber"),
               f.get("ParentId"), f.get("Location"), _int(f.get("Capacity")),
               _int(f.get("PartitionStyle")), _int(f.get("PartitionCount")), f.get("DiskId"),
               f.get("AdapterId"), f.get("RegistryId"), f.get("UserRemovalPolicy"), data)
    else:
        instance = f.get("InstanceId")
        major = f.get("Request.major")
        minor = f.get("Request.minor")
        row = (event_id, ts, computer, user, record, instance, serial_from_instance_id(instance),
               f.get("LifetimeId"), _int(major), _int(minor), _int(f.get("Status")), data)
    return table, row


def create_device_tables(conn):
    """The device-evidence tables (never dropped; a re-parse adds new events)."""
    conn.execute('''CREATE TABLE IF NOT EXISTS partition_diagnostic (
                        EventID INTEGER,
                        EventTimestampUTC TEXT,
                        ComputerName TEXT,
                        RecordNumber INTEGER,
                        DiskNumber INTEGER,
                        BusType INTEGER,
                        Manufacturer TEXT,
                        Model TEXT,
                        Revision TEXT,
                        SerialNumber TEXT,
                        ParentId TEXT,
                        Location TEXT,
                        Capacity INTEGER,
                        PartitionStyle INTEGER,
                        PartitionCount INTEGER,
                        DiskId TEXT,
                        AdapterId TEXT,
                        RegistryId TEXT,
                        UserRemovalPolicy TEXT,
                        EventData TEXT
                      )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS driver_frameworks_usermode (
                        EventID INTEGER,
                        EventTimestampUTC TEXT,
                        ComputerName TEXT,
                        User TEXT,
                        RecordNumber INTEGER,
                        InstanceId TEXT,
                        SerialNumber TEXT,
                        LifetimeId TEXT,
                        MajorCode INTEGER,
                        MinorCode INTEGER,
                        Status INTEGER,
                        EventData TEXT
                      )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS setupapi_dev_log (
                        section_title TEXT,
                        section_kind TEXT,
                        section_subject TEXT,
                        device_instance_id TEXT,
                        serial_number TEXT,
                        section_start_local TEXT,
                        section_start_utc TEXT,
                        section_end_local TEXT,
                        section_end_utc TEXT,
                        exit_status TEXT,
                        boot_session_local TEXT,
                        time_basis TEXT,
                        source_file TEXT,
                        parsed_at TEXT
                      )''')
    for table in DEVICE_TABLE_COLUMNS:
        ensure_identity_index(conn, table, DEVICE_IDENTITY)
    ensure_identity_index(conn, "setupapi_dev_log", SETUPAPI_IDENTITY)


# ------------------------------------------------------ setupapi.dev.log --
# Windows' device-installation log (%SystemRoot%\INF\setupapi.dev.log, with
# its rotated copies setupapi.dev.<date>.log): one section per install, the
# first install of a USB device among them ("Device Install (Hardware
# initiated) - USBSTOR\..."). Its times are the machine's LOCAL time as
# written; section_start_utc is converted by the zone rules that machine kept
# (live: this machine's; offline: the image's SYSTEM hive) and stays empty,
# with time_basis saying why, when those rules are not known.
SETUPAPI_COLUMNS = [
    "section_title", "section_kind", "section_subject", "device_instance_id", "serial_number",
    "section_start_local", "section_start_utc", "section_end_local", "section_end_utc",
    "exit_status", "boot_session_local", "time_basis", "source_file", "parsed_at"]
# A section is the same section in the live log and in its rotated copy.
SETUPAPI_IDENTITY = ["section_title", "section_start_local"]
_SA_STAMP = r"(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?)"
_SA_SECTION = re.compile(r"^>>>\s+\[(?P<title>.*)\]\s*$")
_SA_START = re.compile(r"^>>>\s+Section start " + _SA_STAMP)
_SA_END = re.compile(r"^<<<\s+Section end " + _SA_STAMP)
_SA_EXIT = re.compile(r"^<<<\s+\[Exit status:\s*(?P<status>[^\]]*)\]")
_SA_BOOT = re.compile(r"^\[Boot Session:\s*" + _SA_STAMP + r"\]")


def _sa_local(stamp):
    """'2026/11/05 00:25:21.520' -> '2026-11-05 00:25:21.520' (local, as written)."""
    return stamp.replace("/", "-") if stamp else None


def setupapi_sections(path):
    """Each section of one setupapi.dev*.log: title, local start / end, exit
    status and the boot session it ran in. A section ends at its exit status,
    which Windows writes after "Section end"."""
    boot, cur = None, None
    with open(path, "rb") as fh:
        for raw in fh:
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            m = _SA_BOOT.match(line)
            if m:
                boot = m.group(1)
                continue
            m = _SA_SECTION.match(line)
            if m:
                if cur:
                    yield cur
                cur = {"title": m.group("title").strip(), "start": None, "end": None,
                       "exit": None, "boot": boot}
                continue
            if cur is None:
                continue
            m = _SA_START.match(line)
            if m and cur["start"] is None:
                cur["start"] = m.group(1)
                continue
            m = _SA_END.match(line)
            if m:
                cur["end"] = m.group(1)
                continue
            m = _SA_EXIT.match(line)
            if m:
                cur["exit"] = m.group("status").strip()
                yield cur
                cur = None
    if cur:
        yield cur


def machine_local_to_utc(local):
    """A naive local datetime -> aware UTC, by this machine's zone rules for that date."""
    return local.astimezone(timezone.utc)


def setupapi_rows(path, to_utc=None, time_basis=None, parsed_at=None):
    """setupapi_dev_log rows for one file. ``to_utc``: naive local datetime ->
    aware UTC datetime, or None when the writing machine's zone is unknown."""
    parsed_at = parsed_at or format_forensic_timestamp(get_current_utc())

    def utc(stamp):
        if not stamp or to_utc is None:
            return None
        try:
            dt = datetime.strptime(stamp.split(".")[0], "%Y/%m/%d %H:%M:%S")
            return format_forensic_timestamp(to_utc(dt))
        except (ValueError, OverflowError):
            return None

    out = []
    for sec in setupapi_sections(path):
        title = sec["title"]
        kind, _, subject = title.partition(" - ")
        kind, subject = kind.strip(), subject.strip() or None
        instance = None
        if kind.startswith("Device Install") and subject and "\\" in subject \
                and not subject.lower().endswith(".inf") and ":\\" not in subject:
            instance = subject
        out.append((title, kind, subject, instance, serial_from_instance_id(instance),
                    _sa_local(sec["start"]), utc(sec["start"]), _sa_local(sec["end"]),
                    utc(sec["end"]), sec["exit"], _sa_local(sec["boot"]), time_basis,
                    os.path.basename(path), parsed_at))
    return out


def setupapi_files(folder):
    """setupapi.dev.log and its rotated copies in ``folder``, oldest name first."""
    import glob
    return sorted(glob.glob(os.path.join(folder, "setupapi.dev*.log")))


def read_setupapi_logs(conn, tally, folder=None, to_utc=machine_local_to_utc,
                       time_basis="local time converted by this machine's time zone"):
    """Every setupapi.dev*.log in ``folder`` (default %SystemRoot%\\INF) into
    setupapi_dev_log; returns the sections read."""
    folder = folder or os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "INF")
    read = 0
    for path in setupapi_files(folder):
        try:
            rows = setupapi_rows(path, to_utc, time_basis)
        except OSError as exc:
            print(f"[WARNING] {path}: not read ({exc})")
            continue
        read += len(rows)
        if rows:
            insert_new(conn, "setupapi_dev_log", SETUPAPI_COLUMNS, rows, SETUPAPI_IDENTITY, tally)
    return read


def insert_device_rows(conn, table, rows, tally):
    """The device events not stored yet; returns the number inserted."""
    if not rows:
        return 0
    return insert_new(conn, table, DEVICE_TABLE_COLUMNS[table], rows, DEVICE_IDENTITY, tally)


def read_device_channel(channel, conn, tally, stop_at_record=None, batch=200):
    """One device channel, live, through EvtQuery (newest first). A channel
    that is off or absent is reported and read as empty - not an error.
    ``stop_at_record``: a record number already held (Sentinel's mark); the
    read stops STOP_SLACK_RECORDS below it. Returns the events read."""
    table, ids = DEVICE_CHANNELS[channel]
    query = "*[System[(%s)]]" % " or ".join("EventID=%d" % i for i in ids)
    try:
        handle = win32evtlog.EvtQuery(channel, win32evtlog.EvtQueryChannelPath
                                      | win32evtlog.EvtQueryReverseDirection, query)
    except Exception as exc:
        print(f"[INFO] {channel}: not read ({exc}) - the channel is off or absent here")
        return 0
    floor = None
    if stop_at_record is not None:
        try:
            floor = max(0, int(stop_at_record) - STOP_SLACK_RECORDS)
        except (TypeError, ValueError):
            floor = None
    read = 0
    done = False
    while not done:
        try:
            events = win32evtlog.EvtNext(handle, batch)
        except Exception:
            events = ()
        if not events:
            break
        rows = []
        for ev in events:
            try:
                root = ET.fromstring(win32evtlog.EvtRender(ev, win32evtlog.EvtRenderEventXml))
                got = device_event_row(root)
            except Exception as exc:
                print(f"[WARNING] {channel}: an event not read ({exc})")
                continue
            if got is None:
                continue
            row = got[1]
            record = row[DEVICE_TABLE_COLUMNS[table].index("RecordNumber")]
            if floor is not None and record is not None and record < floor:
                done = True
                break
            rows.append(row)
        read += len(rows)
        insert_device_rows(conn, table, rows, tally)
    return read


# Create the database and tables
def create_database(case_path=None):
    db_path = 'Log_Claw.db'
    if case_path:
        # If a case path is provided, use it for the database
        artifacts_dir = os.path.join(case_path, 'Target_Artifacts')
        # Created, not merely checked: in a new case whose first parse was
        # this one, Target_Artifacts did not exist yet and the database
        # went to the current working folder instead of the case.
        os.makedirs(artifacts_dir, exist_ok=True)
        db_path = os.path.join(artifacts_dir, 'Log_Claw.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Never dropped (see prepare_event_tables): earlier runs' events stay.
    # Create tables for System, Application, and Security logs with UTC timestamps
    cursor.execute('''CREATE TABLE IF NOT EXISTS SystemLogs (
                        EventID INTEGER,
                        Source TEXT,
                        EventType TEXT,
                        Category TEXT,
                        EventTimestampUTC TEXT,  -- Stored in YYYY-MM-DD HH:MM:SS format (UTC)
                        ComputerName TEXT,
                        User TEXT,
                        Keywords TEXT,
                        EventDescription TEXT,
                        RecordNumber INTEGER
                      )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS ApplicationLogs (
                        EventID INTEGER,
                        Source TEXT,
                        EventType TEXT,
                        Category TEXT,
                        EventTimestampUTC TEXT,  -- Stored in YYYY-MM-DD HH:MM:SS format (UTC)
                        ComputerName TEXT,
                        User TEXT,
                        Keywords TEXT,
                        EventDescription TEXT,
                        RecordNumber INTEGER
                      )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS SecurityLogs (
                        EventID INTEGER,
                        Source TEXT,
                        EventType TEXT,
                        Category TEXT,
                        EventTimestampUTC TEXT,  -- Stored in YYYY-MM-DD HH:MM:SS format (UTC)
                        ComputerName TEXT,
                        User TEXT,
                        Keywords TEXT,
                        TaskCategory TEXT,
                        EventDescription TEXT,
                        RecordNumber INTEGER
                      )''')
    create_device_tables(conn)
    conn.commit()
    return conn, cursor, db_path


# Map event types to readable text
def get_event_type(event_type):
    event_type_dict = {
        1: "Error",
        2: "Warning",
        4: "Information",
        8: "Success Audit",
        16: "Failure Audit"
    }
    return event_type_dict.get(event_type, "Unknown")

# Map event categories to readable text
def get_event_category(category):
    category_dict = {
        0: "None",
        1: "Application",
        2: "System",
        3: "Security"
    }
    return category_dict.get(category, "Other")

# What an event means: the shared (provider, EventID) catalogue in
# configs/event_descriptions.json, the same one the offline parser uses. The
# ID-only dictionary that used to be here put wrong words on real rows
# (EventSystem 4625 read "An account failed to log on").
def get_event_description(event_id, source=None, inserts=None):
    from utils.event_descriptions import describe
    return describe(source, event_id, inserts)


def _event_time_utc(event):
    """The event's time in UTC, or None.

    pywin32's TimeGenerated is the machine's LOCAL time with no tzinfo; it was
    labelled UTC unconverted, so every live event was off by the local UTC
    offset (04:25 local recorded as 04:25 UTC, true time 01:25 UTC).
    """
    tg = event.TimeGenerated
    try:
        if getattr(tg, "tzinfo", None) is not None:
            dt = datetime(tg.year, tg.month, tg.day, tg.hour, tg.minute, tg.second,
                          tzinfo=tg.tzinfo).astimezone(timezone.utc)
        else:
            # A naive datetime's astimezone() applies the local rules for THAT
            # date, daylight saving included.
            dt = datetime(tg.year, tg.month, tg.day, tg.hour, tg.minute,
                          tg.second).astimezone(timezone.utc)
        return format_forensic_timestamp(dt)
    except Exception as exc:
        print(f"[WARNING] Event time not converted ({tg!r}): {exc}")
        return None


def _event_sid(event):
    """The SID the event was logged under ('S-1-5-18'), or 'N/A'."""
    sid = getattr(event, "Sid", None)
    if sid is None:
        return "N/A"
    text = str(sid)
    return text[len("PySID:"):] if text.startswith("PySID:") else text

# Records below a mark still read, so a record the mark passed over while the
# log was being written is not missed (Sentinel P7).
STOP_SLACK_RECORDS = 1000


def stop_floor(stop_at_record, oldest, count):
    """The record number the backwards read may stop at, or None to read it all.

    None when no mark was given, or when the log's newest record is below the
    mark: the log was cleared or recreated and its numbers started again, so
    the mark says nothing about it."""
    if stop_at_record is None:
        return None
    try:
        mark = int(stop_at_record)
        newest = int(oldest) + int(count) - 1
    except (TypeError, ValueError):
        return None
    if count <= 0 or newest < mark:
        return None
    return max(0, mark - STOP_SLACK_RECORDS)


# Read event logs and insert into the database
def read_event_logs(log_type, conn, tally=None, legacy=None, stop_at_record=None):
    """Read one live log; store the events the case does not hold yet.

    ``stop_at_record``: a record number already held (Crow-Eye Sentinel's mark).
    The read runs newest first and stops once it reaches that record minus
    STOP_SLACK_RECORDS, instead of reading the whole log every time. What is
    stored does not change: everything above the floor is read and the rows
    are de-duplicated as always."""
    server = 'localhost'
    log_handle = win32evtlog.OpenEventLog(server, log_type)
    flags = win32evtlog.EVENTLOG_BACKWARDS_READ | win32evtlog.EVENTLOG_SEQUENTIAL_READ
    floor = None
    if stop_at_record is not None:
        try:
            floor = stop_floor(stop_at_record,
                               win32evtlog.GetOldestEventLogRecord(log_handle),
                               win32evtlog.GetNumberOfEventLogRecords(log_handle))
        except Exception as exc:
            print(f"[WARNING] {log_type}: the mark was not used ({exc}); reading the whole log")
            floor = None
    table = {"Security": "SecurityLogs", "Application": "ApplicationLogs"}.get(log_type, "SystemLogs")
    tally = tally if tally is not None else Tally()
    legacy = legacy or {}
    aliases = {}

    reached_floor = False
    while not reached_floor:
        events = win32evtlog.ReadEventLog(log_handle, flags, 0)
        if not events:
            break
        rows = []

        for event in events:
            if floor is not None and event.RecordNumber < floor:
                reached_floor = True
                break
            try:
                event_id = event.EventID & 0xFFFF
                source = event.SourceName
                event_type = get_event_type(event.EventType)
                category = get_event_category(event.EventCategory)
                
                # True UTC (see _event_time_utc). A time that cannot be
                # converted stays empty: it used to become the parse time,
                # a fabricated timestamp that looked real.
                utc_time = _event_time_utc(event)

                computer = event.ComputerName
                inserts = list(event.StringInserts or [])
                keywords = ",".join(str(i) for i in inserts) if inserts else "N/A"
                event_description = get_event_description(event_id, source, inserts)
                # The account the event was logged under. Insert 1 was used
                # for every log, which is SubjectUserName for most Security
                # events but an arbitrary value ('5', '0') everywhere else.
                user = _event_sid(event)

                if log_type == 'Security':
                    if len(inserts) > 1 and inserts[1] and inserts[1] != "-":
                        user = inserts[1]          # SubjectUserName
                    task_category = event.EventCategory
                    rows.append((event_id, source, event_type, category, utc_time,
                                 computer, user, keywords, task_category, event_description,
                                 event.RecordNumber))
                else:  # System and Application logs
                    rows.append((event_id, source, event_type, category, utc_time,
                                 computer, user, keywords, event_description,
                                 event.RecordNumber))
                                 
            except Exception as e:
                print(f"Error processing event: {str(e)}")
                continue
        for source in {r[1] for r in rows} - set(aliases):
            aliases[source] = provider_name(log_type, source)
        insert_event_rows(conn, table, rows, tally, legacy.get(table, False), aliases)

    win32evtlog.CloseEventLog(log_handle)
    return tally

# Main function to create database and read logs
def main(case_path=None, stop_at_records=None):
    """``stop_at_records``: {"System"|"Application"|"Security"|<device channel>:
    record number}, the marks a caller already holds (Crow-Eye Sentinel); each
    log's read stops there. None reads every log whole, as the desktop always
    does. The device channels (DEVICE_CHANNELS) are keyed by their full name."""
    marks = stop_at_records if isinstance(stop_at_records, dict) else {}
    conn, cursor, db_path = create_database(case_path)
    tally = Tally()          # first: it lists the identity indexes created below
    legacy = prepare_event_tables(conn)

    print("Reading System Logs...")
    read_event_logs('System', conn, tally, legacy, marks.get('System'))

    print("\nReading Application Logs...")
    read_event_logs('Application', conn, tally, legacy, marks.get('Application'))

    print("\nReading Security Logs...")
    read_event_logs('Security', conn, tally, legacy, marks.get('Security'))

    for channel in DEVICE_CHANNELS:
        print("\nReading %s..." % channel)
        n = read_device_channel(channel, conn, tally, marks.get(channel))
        print("%s: %d event(s)" % (channel, n))

    print("\nReading setupapi.dev.log...")
    n = read_setupapi_logs(conn, tally)
    print("setupapi.dev.log: %d section(s)" % n)

    conn.commit()
    conn.close()

    tot = tally.totals()
    print("Events read: %d - new: %d, already in the database: %d"
          % (tot["parsed"], tot["inserted"], tot["duplicates"]))
    print(f"\033[92m\nParsing logs has been completed by Crow Eye\nDatabase saved to: {db_path}\033[0m")
    # Counts for Parse Status and the custody record (it returned nothing).
    return tally.as_result(success=True, output_path=db_path)

if __name__ == "__main__":
    main()
