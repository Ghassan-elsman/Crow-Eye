try:
    import win32evtlog
except ImportError:
    win32evtlog = None
import sqlite3
import os
import sys
from datetime import datetime, timezone

# Add the parent directory to sys.path to import utils
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.time_utils import ensure_utc, format_timestamp, format_forensic_timestamp, get_current_forensic_timestamp
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


def insert_event_rows(conn, table, rows, tally, legacy=False):
    """Insert the events not stored yet; returns the number inserted.

    ``legacy``: the table holds rows from before RecordNumber was recorded.
    Such a row cannot be matched by number, so an event is also skipped when a
    numberless row with the same time, provider, ID and text exists - the
    first re-parse of an older case does not store its events a second time.
    """
    cols = EVENT_TABLE_COLUMNS[table]
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

# Read event logs and insert into the database
def read_event_logs(log_type, conn, tally=None, legacy=None):
    """Read one live log; store the events the case does not hold yet."""
    server = 'localhost'
    log_handle = win32evtlog.OpenEventLog(server, log_type)
    flags = win32evtlog.EVENTLOG_BACKWARDS_READ | win32evtlog.EVENTLOG_SEQUENTIAL_READ
    table = {"Security": "SecurityLogs", "Application": "ApplicationLogs"}.get(log_type, "SystemLogs")
    tally = tally if tally is not None else Tally()
    legacy = legacy or {}

    while True:
        events = win32evtlog.ReadEventLog(log_handle, flags, 0)
        if not events:
            break
        rows = []

        for event in events:
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
        insert_event_rows(conn, table, rows, tally, legacy.get(table, False))

    win32evtlog.CloseEventLog(log_handle)
    return tally

# Main function to create database and read logs
def main(case_path=None):
    conn, cursor, db_path = create_database(case_path)
    tally = Tally()          # first: it lists the identity indexes created below
    legacy = prepare_event_tables(conn)

    print("Reading System Logs...")
    read_event_logs('System', conn, tally, legacy)

    print("\nReading Application Logs...")
    read_event_logs('Application', conn, tally, legacy)

    print("\nReading Security Logs...")
    read_event_logs('Security', conn, tally, legacy)

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
