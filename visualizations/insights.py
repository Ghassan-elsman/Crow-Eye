"""One shape for every dashboard's insights, so every one can be opened.

An insight used to be a bare integer. `prefetch_bridge` returned
``{"userTemp": 19}``, and the loop that counted those 19 programs threw away
which ones they were - so the card could state a number and the analyst had no
way to ask the obvious next question, *which files?*. `mftusn_bridge` was a
step worse: its anomaly counts came from ``SELECT COUNT(*)``, so the rows were
never materialised at all.

`browser_bridge` was the one that got it right - it returned a list of orphan
domains **plus** a count, and degraded honestly to "+N more" when it had only
the count. This module is that shape, made general:

    {"count": 19, "subjects": [{...}, ...], "truncated": false}

`count` is the real total and is what the tile shows. `subjects` is who it is
about, capped so a pathological case cannot push megabytes through the
QWebChannel, and `truncated` says plainly when the list is shorter than the
count rather than letting the UI imply it is complete.

A subject is deliberately small:

    {"label": "the thing an analyst reads",
     "open":  "the id the dashboard's detail modal takes, or None",
     "note":  "one short line of context, optional"}

`open` is what makes an insight a drill-down rather than a list: prefetch's
detail modal opens on a prefetch filename, so an insight about programs run
from Temp hands back those filenames and the existing modal does the rest.
"""

SUBJECT_CAP = 60


def subject(label, open_id=None, note=""):
    """One row inside an insight. `open_id` opens the dashboard's detail modal."""
    out = {"label": label}
    if open_id:
        out["open"] = open_id
    if note:
        out["note"] = note
    return out


def insight(count, subjects=(), cap=SUBJECT_CAP):
    """An insight the analyst can open: the number, and who it is about.

    `count` is passed separately from `subjects` on purpose. The count is over
    every matching record; the subject list is capped. Deriving the count from
    ``len(subjects)`` would silently under-report the moment the cap bit.
    """
    subs = list(subjects)[:cap]
    total = int(count or 0)
    return {"count": total, "subjects": subs, "truncated": total > len(subs)}


def plain(count):
    """An insight with nothing to open - a measurement, not a set of records.

    Kept explicit so the UI can tell "nothing matched" from "we never collected
    the subjects", which look identical if both are just an empty list.
    """
    return {"count": int(count or 0), "subjects": [], "truncated": False}
