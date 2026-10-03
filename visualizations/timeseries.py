"""A heat strip's x axis is time, so every day in the range must be on it.

`SELECT date(timestamp) d, COUNT(*) FROM ... GROUP BY d` gives you only the days
that *had* activity. Plot that directly and the strip stops being a time axis
and becomes an ordinal index of active days: two neighbouring cells can be
months apart, and a date scale spaced evenly across them says otherwise.

Measured on one real case before this existed:

    browser      134 cells across 226 calendar days   (92 days erased)
    prefetch     170 cells across 213 days            (43 erased)
    viz           58 cells across  61 days             (3 erased)
    shellitems   146 cells across 4,568 days          (most of 12 years erased)
    lnkjl         70 cells across 4,568 days

A quiet stretch is usually the thing an investigator came to find, so erasing it
is the opposite of useful.

**One cell is one day. Always.** An earlier version of this module widened the
cell to a week or a month when the range was long, so Shell Items' twelve years
became 151 month cells that still fit the pane. That trades the question away:
a reader cannot see which *days* were quiet if a cell is a month. A range too
long to fit does not get a different unit - the strip scrolls sideways instead,
which is a front-end concern (`DayAxis.jsx`), not a data one. So this module has
no notion of granularity at all, and no bridge chooses one.
"""

from datetime import date, timedelta


def _parse(value):
    """'YYYY-MM-DD' (or a longer timestamp) -> date, or None."""
    text = str(value or "")[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def day_keys(start, end):
    """Every date between start and end inclusive, with none missing."""
    a, b = _parse(start), _parse(end)
    if not a or not b or b < a:
        return []
    out, cur = [], a
    while cur <= b:
        out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out


def axis_range(args, *counts):
    """The span the strip should cover: the filter's range, else the data's.

    The filter wins when it is set, because an analyst who narrowed to a week
    means that week - including the days in it with nothing on them, which are
    often the point. With no filter, fall back to the first and last day that
    carry anything, so an empty case does not produce an axis out of nothing.

    The `or` is the whole rule, per side: a side the filter set wins, a side it
    left blank falls back to the data.
    """
    start = str((args or {}).get("start") or "")[:10]
    end = str((args or {}).get("end") or "")[:10]
    seen = [str(k)[:10] for c in counts for k in (c or {})]
    seen = [s for s in seen if _parse(s)]
    if not seen:
        return start, end
    return start or min(seen), end or max(seen)


def span(*counts):
    """The first and last day carrying anything, across several count dicts.

    For a series whose range is its own data rather than the analyst's filter -
    MFT Standard-Info times run back to the machine's build, which has nothing
    to do with the journal window beside it.
    """
    return axis_range({}, *counts)


def densify(counts, start, end, key="day"):
    """{day: n} -> an ordered list covering every day in the range, zeros included.

    `counts` is keyed by date string - whatever a `GROUP BY date(...)` produced.
    Returns ``[{<key>: 'YYYY-MM-DD', 'value': n}, ...]``; `key` is the field name
    the dashboard already uses ("day" for five of the six, "key" for MFT/USN).
    """
    rolled = {}
    for raw, n in (counts or {}).items():
        d = _parse(raw)
        if d is None:
            continue
        k = d.isoformat()
        rolled[k] = rolled.get(k, 0) + (n or 0)
    return [{key: k, "value": rolled.get(k, 0)} for k in day_keys(start, end)]


def densify_series(series, start, end, key="day", field="days"):
    """The same, for a dict of named series sharing one axis.

    `series` is ``{name: {day: n}}``. Every series gets the identical day list,
    which is what lets a stack of strips line up cell-for-cell - the property
    that makes them comparable at a glance.

    `key` and `field` name the output fields, because the USN strip calls them
    `key` and `buckets` where the other five say `day` and `days`.
    """
    keys = day_keys(start, end)
    out = {}
    for name, counts in (series or {}).items():
        rolled = {}
        for raw, n in (counts or {}).items():
            d = _parse(raw)
            if d is None:
                continue
            rolled[d.isoformat()] = rolled.get(d.isoformat(), 0) + (n or 0)
        days = [{key: k, "value": rolled.get(k, 0)} for k in keys]
        out[name] = {field: days, "max": max((d["value"] for d in days), default=0)}
    return out


def densify_table(columns, start, end, key="day"):
    """The same, for measurements that share a row rather than a strip.

    `columns` is ``{name: {day: n}}`` and each result row carries every name -
    ``[{<key>: ..., 'created': n, 'modified': n}, ...]`` - which is the shape a
    stacked bar chart reads, as against `densify_series`'s one strip per name.
    """
    names = list((columns or {}).keys())
    rolled = {}
    for name in names:
        acc = {}
        for raw, n in (columns[name] or {}).items():
            d = _parse(raw)
            if d is None:
                continue
            acc[d.isoformat()] = acc.get(d.isoformat(), 0) + (n or 0)
        rolled[name] = acc
    rows = []
    for k in day_keys(start, end):
        row = {key: k}
        for name in names:
            row[name] = rolled[name].get(k, 0)
        rows.append(row)
    return rows
