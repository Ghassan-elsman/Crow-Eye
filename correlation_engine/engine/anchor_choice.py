"""Which feather a match is anchored on: the Wing's own choice, in both engines.

A Wing names an anchor priority, artifact types best first (Logs before Prefetch before
Registry, ...), and may name one feather to anchor every match on. Neither engine read either:
the Time engine anchored on whichever feather came first in a dict, the Identity engine on the
first in a list, so the anchor - and with it the match's time in the Time engine - followed load
order instead of what the analyst chose. The validator even required the priority to be set.
"""

from typing import Any, Iterable, List


def _priority(wing: Any) -> List[str]:
    rules = getattr(wing, 'correlation_rules', None)
    prio = getattr(rules, 'anchor_priority', None) if rules is not None else None
    if prio is None:
        prio = getattr(wing, 'anchor_priority', None)
    if isinstance(prio, dict):                       # older shape: {artifact_type: rank}
        prio = [k for k, _v in sorted(prio.items(), key=lambda kv: kv[1])]
    return [str(p).lower() for p in (prio or [])]


def _override(wing: Any) -> str:
    rules = getattr(wing, 'correlation_rules', None)
    value = getattr(rules, 'anchor_feather_override', '') if rules is not None else ''
    return str(value or getattr(wing, 'anchor_feather_override', '') or '').lower()


def _types(wing: Any) -> dict:
    out = {}
    for spec in getattr(wing, 'feathers', None) or []:
        fid = getattr(spec, 'feather_id', None) or getattr(spec, 'feather_config_name', None)
        kind = getattr(spec, 'artifact_type', None)
        if fid and kind:
            out[str(fid).lower()] = str(kind).lower()
    return out


def choose_anchor(feather_ids: Iterable[str], wing: Any) -> str:
    """The feather to anchor on among `feather_ids`: the Wing's
    anchor_feather_override when present among them, else the one whose
    artifact type ranks highest in the Wing's anchor_priority, ties (and
    feathers of unlisted types) keeping their given order. "" when there are
    no feathers."""
    ids = list(feather_ids)
    if not ids:
        return ''
    if wing is None:
        return ids[0]
    override = _override(wing)
    if override:
        for fid in ids:
            if str(fid).lower() == override:
                return fid
    prio = _priority(wing)
    if not prio:
        return ids[0]
    types = _types(wing)
    last = len(prio)

    def rank(item):
        index, fid = item
        kind = types.get(str(fid).lower(), '')
        return (prio.index(kind) if kind in prio else last, index)
    return min(enumerate(ids), key=rank)[1]
