"""Every column of the row behind a detail panel.

Each dashboard's detail modal is hand-curated: it shows the fields someone
decided were worth reading, shaped into run-time lists, volume blocks and
resource tables. That is the right default and it means anything the parser
stored but the panel never learned about is invisible - the analyst cannot
tell "this artifact does not record that" from "this panel does not show it".

So every panel also carries the underlying row verbatim. The curated reading
stays on top; this is what sits under it. The timeline already worked this way
(`timeline_bridge.py` `getEventDetail` feeding `EventDetailModal`), so this is
that idea, not a new one.

**Withholding.** A raw dump of a browser row would put encrypted passwords,
cookie values and saved-card fragments on screen and into reports. Those live
in the database and are reached deliberately through the evidence path, never
rendered because a panel happened to select `*`. Columns named below are
reported as present-but-withheld rather than dropped, because "this row has a
stored password" is itself a finding; the value is not.
"""

# Column names whose VALUE must never be rendered. Matched case-insensitively
# against the exact column name, and also as a suffix, so
# `password_encrypted_b64` and `card_number_encrypted_b64` are both caught.
WITHHELD_EXACT = {
    "password", "password_value", "password_encrypted_b64",
    "username_value", "encrypted_value_b64", "os_crypt_key_b64",
    "card_number_encrypted_b64", "last_four", "value",
    "token", "secret", "cookie_value",
}
WITHHELD_SUFFIX = ("_encrypted_b64", "_password", "_secret", "_token", "_key_b64")

# Bookkeeping the analyst does not need in a detail panel.
SKIP = {"parsed_at"}

MAX_LEN = 2000


def _is_withheld(name):
    n = (name or "").strip().lower()
    return n in WITHHELD_EXACT or n.endswith(WITHHELD_SUFFIX)


def _render(value):
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray)):
        return "<%d bytes>" % len(value)
    text = str(value)
    if len(text) > MAX_LEN:
        return text[:MAX_LEN] + "... (%d more characters)" % (len(text) - MAX_LEN)
    return text


def raw_record(row, table="", skip=()):
    """A sqlite3.Row (or dict) as ordered, renderable name/value pairs.

    Returns ``{"table": ..., "fields": [{"name", "value", "withheld"}]}``.
    Empty columns are kept: "this column exists and is blank" and "this column
    does not exist" are different facts, and only one of them is a parser bug.
    """
    if row is None:
        return None
    try:
        names = list(row.keys())
    except AttributeError:
        names = list(row)
    drop = SKIP | set(skip or ())
    fields = []
    for name in names:
        if name in drop:
            continue
        if _is_withheld(name):
            fields.append({"name": name, "value": "", "withheld": True})
            continue
        fields.append({"name": name, "value": _render(row[name]), "withheld": False})
    return {"table": table, "fields": fields}


# A detail panel that aggregates can face thousands of rows - a SRUM app spans
# five providers, a browser domain spans every table that mentions it. The cap
# is the same idea as `insights.SUBJECT_CAP`: show a usable number, say plainly
# that it is not all of them, and never push megabytes through the QWebChannel.
MAX_RECORDS = 40


def source_records(rows, table="", skip=(), cap=MAX_RECORDS, label_of=None, total=None):
    """The rows behind a panel whose subject has no single source row.

    `rows` is either an iterable of rows from one table, or an iterable of
    ``(table, row)`` pairs when the subject is assembled from several. Returns
    ``{"records": [...], "total": n, "truncated": bool}`` where each record is
    a `raw_record()` plus an optional `label` naming which artifact it came
    from.

    `total` overrides the count when the caller already limited its own query:
    counting what was fetched would report "showing 40 of 600" for an app with
    thousands of rows, which is a smaller lie than the one it replaced but
    still a lie.

    A Shell Item has one registry row and uses `raw_record` directly. An LNK
    target is reached through LNK_Files, Automatic_JumpLists, Custom_JumpLists
    and JLCE at once, so there is no one row to show - and picking an arbitrary
    one would be less honest than showing all of them.
    """
    out, seen = [], 0
    for item in rows or ():
        seen += 1
        if len(out) >= cap:
            continue
        if isinstance(item, tuple) and len(item) == 2:
            tname, row = item
        else:
            tname, row = table, item
        rec = raw_record(row, tname, skip=skip)
        if rec is None:
            seen -= 1
            continue
        if label_of is not None:
            rec["label"] = label_of(item)
        out.append(rec)
    n = seen if total is None else max(total, seen)
    return {"records": out, "total": n, "truncated": n > len(out)}
