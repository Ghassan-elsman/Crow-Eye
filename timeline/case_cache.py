"""Answers of the timeline's whole-case questions, kept beside the case until
a database changes.

Why: opening the timeline asks the whole case two questions before anything
is drawn, the earliest and latest times (getTimeBounds: 34 MIN/MAX queries)
and the activity per day (getAggregatedCounts: 14 grouped scans). On a real
case that was 3.4 s and 2.0 s on every opening, for answers that only change
when a parse writes a database.

Each answer is stored in ``<case>/Timeline/answers.json``. The store itself
(the signature of the case's databases, the stale check, the file) is
utils/case_cache.py, shared with the MFT/USN dashboard; this module keeps the
timeline's place for it.
"""

from timeline.day_index import DIRNAME
from utils import case_cache as _store

FILENAME = "answers.json"
signature = _store.signature


def _path(artifacts_dir):
    return _store.path_for(artifacts_dir, DIRNAME, FILENAME)


def get(artifacts_dir, key):
    """The stored answer for `key`, or None when absent or stale."""
    return _store.get(artifacts_dir, key, DIRNAME, FILENAME)


def put(artifacts_dir, key, answer, sig=None):
    """Store `answer` for `key`. `sig` is the signature taken BEFORE the
    answer was computed, so a database written meanwhile makes it stale."""
    _store.put(artifacts_dir, key, answer, DIRNAME, FILENAME, sig=sig)
