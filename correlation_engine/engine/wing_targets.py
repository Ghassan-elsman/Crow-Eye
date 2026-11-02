"""A Wing's targets: the application, file path and Event IDs an analyst narrowed it to.

The Wing Creator offers "Apply to: specific application" with a name, a path filter and Event IDs,
and the validator checks them, but neither the Time nor the Identity engine read them: only the
legacy engine did, and it queried an `application` column today's feathers do not have. So
"Specific application: chrome.exe" returned every application.

Matching, case-insensitive:
  application  a pattern with * or ? is a wildcard (fnmatch) against the whole value and its file
               name; otherwise the value or its file name must equal it, and a bare name also
               matches with its extension ("chrome" finds chrome.exe).
  file path    a wildcard pattern as above; otherwise the value must contain it.
  Event IDs    comma-separated; a record with an EventID field must carry one of them. A record
               with none (a Prefetch row) is not judged on Event IDs.
"""

import fnmatch
import ntpath
from typing import Any, Iterable, List, Optional

_PATH_HINTS = ('path', 'location', 'directory', 'folder')
_EVENT_FIELDS = ('EventID', 'event_id', 'EventId', 'eventid')


def _rules(wing: Any):
    return getattr(wing, 'correlation_rules', None) or wing


def _get(obj: Any, name: str, default=''):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


class WingTargets:
    """The targets of one Wing, ready to test records or identities."""

    def __init__(self, wing: Any, identity_fields: Optional[Iterable[str]] = None):
        rules = _rules(wing) if wing is not None else None
        apply_to = str(_get(rules, 'apply_to', 'all') or 'all').lower() if rules is not None else 'all'
        app = str(_get(rules, 'target_application', '') or '').strip() if rules is not None else ''
        self.application = app.lower() if apply_to == 'specific' and app not in ('', '*') else ''
        path = str(_get(rules, 'target_file_path', '') or '').strip() if rules is not None else ''
        self.file_path = path.lower() if path not in ('', '*') else ''
        ids = str(_get(rules, 'target_event_id', '') or '') if rules is not None else ''
        self.event_ids = {i.strip() for i in ids.split(',') if i.strip()}
        self.identity_fields: List[str] = list(identity_fields or ())

    @property
    def active(self) -> bool:
        return bool(self.application or self.file_path or self.event_ids)

    def describe(self) -> str:
        parts = []
        if self.application:
            parts.append("application %s" % self.application)
        if self.file_path:
            parts.append("path %s" % self.file_path)
        if self.event_ids:
            parts.append("Event ID %s" % ",".join(sorted(self.event_ids)))
        return ", ".join(parts)

    # -- matching ------------------------------------------------------------------
    @staticmethod
    def _wild(pattern: str) -> bool:
        return '*' in pattern or '?' in pattern

    def _app_hit(self, value: str) -> bool:
        v = value.strip().lower()
        if not v:
            return False
        base = ntpath.basename(v.replace('/', '\\'))
        if self._wild(self.application):
            return fnmatch.fnmatch(v, self.application) or fnmatch.fnmatch(base, self.application)
        if v == self.application or base == self.application:
            return True
        return '.' not in self.application and base.rsplit('.', 1)[0] == self.application

    def _path_hit(self, value: str) -> bool:
        v = value.strip().lower()
        if not v:
            return False
        if self._wild(self.file_path):
            return fnmatch.fnmatch(v, self.file_path)
        return self.file_path in v

    def identity_matches(self, name: Any, path: Any) -> bool:
        """For an identity (the Identity engine): its name or path against the
        application target, its path against the path target."""
        name, path = str(name or ''), str(path or '')
        if self.application and not (self._app_hit(name) or self._app_hit(path)):
            return False
        if self.file_path and not self._path_hit(path):
            return False
        return True

    def record_matches(self, record: dict) -> bool:
        """For one feather row (the Time engine)."""
        if not isinstance(record, dict):
            return True
        if self.event_ids:
            for field in _EVENT_FIELDS:
                if field in record and record[field] not in (None, ''):
                    if str(record[field]).strip() not in self.event_ids:
                        return False
                    break
        if self.application:
            fields = self.identity_fields or list(record)
            if not any(self._app_hit(str(record[f])) for f in fields
                       if f in record and record[f] not in (None, '')):
                return False
        if self.file_path:
            if not any(self._path_hit(str(v)) for k, v in record.items()
                       if v not in (None, '') and any(h in str(k).lower() for h in _PATH_HINTS)):
                return False
        return True
