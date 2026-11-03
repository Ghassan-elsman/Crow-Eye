"""Shadow Copies: every copy of a volume, what it takes and where, what made it, and what changed.

The window answers, top to bottom:

- where things sit: the volume drawn to scale with $MFT, the USN journal and each copy's own store
  at their real positions (volume_layout / shadow_copies), the selected copy outlined;
- how much space: shadow storage as a gauge, one segment per copy (its store), against what
  Windows has allocated and the maximum it may use;
- when: the copies on a time axis up to now, the copies Windows does not expose drawn hollow, and
  every removal Windows logged (volsnap 33 / 95 ...) as a tick - so a copy that vanished with no
  logged removal stands out;
- each copy in full: number, created (UTC), age, size, exposed or hidden, what triggered it (the
  requester's own command line from VSS event 8231, the restore point it belongs to);
- what changed: chosen copies compared with each other and with now, for the whole volume or one
  folder, as a folder tree with each folder's size in every state and its added / deleted / changed
  counts per interval, and the files of the selected folder and interval.

Sizes are always in B / KB / MB / GB / TB. Text never sits inside a mark too small for it.
"""
from __future__ import annotations

import datetime
import os
import sqlite3
from typing import List, Optional

from PyQt5 import QtCore, QtGui, QtWidgets

try:
    from ui import app_theme as _theme
except Exception:   # pragma: no cover
    _theme = None

from Artifacts_Collectors.shadow_copies import size_text

MFT_C, USN_C, VSS_C = "#F472B6", "#A3E635", "#FACC15"
SEL_C = "#F8FAFC"
REMOVAL_C = "#94A3B8"
NOW_C = "#22D3EE"                 # now: the live volume, as in the File Browser's sources
MUTED_C, BODY_C, CAPTION_C = "#94A3B8", "#E2E8F0", "#A5B4FC"
TRACK_C, USED_C, EDGE_C = "#0B1220", "#1B2538", "#2A3650"
LABEL_W = 156                     # the left column of captions


def _utc(text) -> Optional[datetime.datetime]:
    try:
        return datetime.datetime.strptime(str(text)[:19], "%Y-%m-%dT%H:%M:%S")
    except (TypeError, ValueError):
        return None


def _age(text) -> str:
    t = _utc(text)
    if t is None:
        return ""
    d = datetime.datetime.utcnow() - t
    if d.days >= 1:
        return "%d day%s" % (d.days, "" if d.days == 1 else "s")
    h = d.seconds // 3600
    return "%d h %d min" % (h, (d.seconds % 3600) // 60) if h else "%d min" % (d.seconds // 60)


def _copy_name(c) -> str:
    return ("#%s" % c["number"]) if c.get("number") else "hidden %s" % (c.get("created") or "")[11:16]


def _shade(i, n):
    """Older copies darker, the newest brightest: one hue, shades by age (one meaning: a copy)."""
    base = QtGui.QColor(VSS_C)
    f = 0.45 + 0.55 * (i + 1) / max(1, n)
    return QtGui.QColor(int(base.red() * f), int(base.green() * f), int(base.blue() * f))


# Tick steps for the timeline axis, and how each is written.
_STEPS = ((600, "%H:%M"), (1800, "%H:%M"), (3600, "%H:%M"), (2 * 3600, "%H:%M"), (6 * 3600, "%d %b %H:%M"),
          (12 * 3600, "%d %b %H:%M"), (86400, "%d %b"), (2 * 86400, "%d %b"), (7 * 86400, "%d %b"),
          (30 * 86400, "%b %Y"))


def _font(px, bold=False, upper=False):
    if _theme is not None:
        return _theme.font("ui", px, QtGui.QFont.Bold if bold else QtGui.QFont.Normal, upper=upper,
                           spacing=106 if upper else 100)
    f = QtGui.QFont("Segoe UI", max(7, px - 4))
    f.setBold(bold)
    if upper:
        f.setCapitalization(QtGui.QFont.AllUppercase)
    return f


HELP_HTML = """<b>What a shadow copy is.</b> Windows keeps earlier versions of a volume by copying a block aside just before
it is overwritten (copy-on-write). Each copy is a moment the volume can be read back as it was: files deleted
since, older versions of changed files, the registry and logs of that day.<br><br>
<b>Exposed or hidden.</b> Windows lists the copies it <i>exposes</i> as devices (filled dots). Crow-Eye also reads
the volume's own VSS catalog, which holds copies Windows no longer lists (hollow rings) - they are still on the
disk and Crow-Eye rebuilds them from their stores with its own reader.<br><br>
<b>The map.</b> The top bar is the volume to scale: $MFT and the USN journal in the upper lane, each copy's
store in the lower lane where it really sits. The gauge below is the shadow storage: one segment per copy against
what Windows allocated (dashed) and its maximum (the whole bar). The timeline places every copy, with the
removals Windows logged as grey diamonds - a copy that vanished with no logged removal was deleted by something
else (vssadmin, wmic: MITRE T1490).<br><br>
<b>Why a copy exists.</b> Select a copy: every record that explains it is listed under the table with its source -
System Restore's own metadata, its events (8194, 8300-8302), the VSS request event (8231), the VSS diagnostics
key, the copy's store flags and Crow-Eye's own records. Many copies carry none; that is common and proves
nothing.<br><br>
<b>What changed.</b> Tick copies, choose the whole volume or one folder, and Compare: each moment's $MFT is read
in step and every folder's size and its added / deleted / changed counts are shown, with the files themselves.
Browse this copy opens it in the Live File Browser to read or recover files."""


def _h_escape(text):
    import html as _h
    return _h.escape(str(text or ""))


def _why_html(c) -> str:
    """The selected copy's provenance: the summary, then each record with where it comes from."""
    import html as _h
    if c.get("provenance") is None:
        return ("<p style='color:#F8FAFC; font-size:14px'><b>%s</b></p><p style='color:#94a3b8'>Reading what made "
                "this copy: System Restore's records, the VSS events and diagnostics key, the copy's own flags..."
                "</p>" % _h_escape(_copy_name(c)))
    p = c.get("provenance") or {}
    ev = p.get("evidence") or []
    out = ["<p style='color:#F8FAFC; font-size:14px'><b>%s</b> &nbsp; <span style='color:#94a3b8'>%s UTC"
           " &middot; %s &middot; %s</span></p>" % (
               _h.escape(_copy_name(c)), _h.escape((c.get("created") or "").replace("T", " ").rstrip("Z")),
               _h.escape(size_text(c.get("store_bytes"))),
               "exposed by Windows" if c.get("exposed") else "in the catalog only (hidden)")]
    out.append("<p style='color:#E2E8F0'>%s</p>" % _h.escape(p.get("summary") or c.get("trigger") or ""))
    if ev:
        out.append("<table cellspacing='0' cellpadding='4'>")
        for e in ev:
            out.append("<tr><td style='color:#A5B4FC; white-space:nowrap; vertical-align:top'>%s</td>"
                       "<td style='color:#CBD5E1'>%s</td></tr>" % (_h.escape(e["source"]), _h.escape(e["text"])))
        out.append("</table>")
    else:
        out.append("<p style='color:#94a3b8'>No record on this machine explains it.</p>")
    out.append("<p style='color:#64748b'>Shadow copy %s &middot; snapshot set %s</p>" % (
        _h.escape(c.get("shadow_id") or ""), _h.escape(c.get("set_id") or "")))
    return "".join(out)


class VolumeMap(QtWidgets.QWidget):
    """The volume to scale, the storage gauge, and the timeline - painted, labels outside marks."""

    copy_clicked = QtCore.pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.copies: List[dict] = []
        self.layout_data: dict = {}
        self.removals: List[dict] = []
        self.volume_size = 0
        self.used = 0
        self.selected = -1
        self._hits = []
        self.setMouseTracking(True)
        self.setMinimumHeight(316)
        self.cap_font, self.body_font, self.small_font = _font(11, True, True), _font(13), _font(12)

    def set_data(self, copies, layout_data, removals, volume_size, used):
        self.copies, self.layout_data, self.removals = copies, layout_data or {}, removals or []
        self.volume_size, self.used = volume_size or 1, used or 0
        self.update()

    def set_empty_note(self, text):
        """What the timeline says when the volume has no copies (why, from Windows' own logs)."""
        self.empty_note = text or ""
        self.update()

    def select(self, i):
        self.selected = i
        self.update()

    # ---- painting helpers -------------------------------------------------------------------
    def _caption(self, g, y, text, sub=None):
        g.setFont(self.cap_font)
        g.setPen(QtGui.QColor(CAPTION_C))
        g.drawText(QtCore.QRectF(0, y, LABEL_W - 14, 18), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, text)
        if sub:
            g.setFont(self.small_font)
            g.setPen(QtGui.QColor(MUTED_C))
            g.drawText(QtCore.QRectF(0, y + 18, LABEL_W - 14, 18), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, sub)

    def _legend(self, g, x, y, colour, text, shape="box"):
        """One legend entry at (x, y); returns where the next one starts."""
        g.setPen(QtCore.Qt.NoPen)
        if shape == "box":
            g.setBrush(QtGui.QColor(colour))
            g.drawRoundedRect(QtCore.QRectF(x, y + 3, 11, 11), 3, 3)
        elif shape == "dot":
            g.setBrush(QtGui.QColor(colour))
            g.drawEllipse(QtCore.QPointF(x + 5.5, y + 8.5), 5, 5)
        elif shape == "ring":
            g.setPen(QtGui.QPen(QtGui.QColor(colour), 1.6))
            g.setBrush(QtCore.Qt.NoBrush)
            g.drawEllipse(QtCore.QPointF(x + 5.5, y + 8.5), 4.5, 4.5)
        elif shape == "outline":
            g.setPen(QtGui.QPen(QtGui.QColor(colour), 1.5))
            g.setBrush(QtCore.Qt.NoBrush)
            g.drawRoundedRect(QtCore.QRectF(x + 0.5, y + 3.5, 10, 10), 2, 2)
        elif shape == "diamond":
            g.setBrush(QtGui.QColor(colour))
            g.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(x + 5.5, y + 3), QtCore.QPointF(x + 11, y + 8.5),
                                           QtCore.QPointF(x + 5.5, y + 14), QtCore.QPointF(x, y + 8.5)]))
        g.setFont(self.small_font)
        g.setPen(QtGui.QColor(MUTED_C))
        tw = QtGui.QFontMetrics(self.small_font, self).horizontalAdvance(text)
        g.drawText(QtCore.QRectF(x + 17, y, tw + 4, 17), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, text)
        return x + 17 + tw + 22

    def _track(self, g, rect):
        path = QtGui.QPainterPath()
        path.addRoundedRect(rect, 7, 7)
        g.fillPath(path, QtGui.QColor(TRACK_C))
        return path

    def _edge(self, g, path):
        g.setClipping(False)
        g.setPen(QtGui.QPen(QtGui.QColor(EDGE_C), 1))
        g.setBrush(QtCore.Qt.NoBrush)
        g.drawPath(path)

    def paintEvent(self, _event):
        g = QtGui.QPainter(self)
        g.setRenderHint(QtGui.QPainter.Antialiasing)
        self._hits = []
        x0, x1 = LABEL_W, self.width() - 22
        w = max(1, x1 - x0)
        muted, body = QtGui.QColor(MUTED_C), QtGui.QColor(BODY_C)
        n = len(self.copies)

        # 1. the volume, to scale: $MFT and the USN journal on the top lane, each copy's store below
        y = 4
        letter = self.copies[0]["volume"] if self.copies and self.copies[0].get("volume") else ""
        self._caption(g, y + 2, "Volume %s:" % letter if letter else "Volume", size_text(self.volume_size))
        bar = QtCore.QRectF(x0, y, w, 38)
        path = self._track(g, bar)
        g.setClipPath(path)
        if self.used:
            g.fillRect(QtCore.QRectF(x0, y, w * min(1.0, self.used / self.volume_size), 38), QtGui.QColor(USED_C))

        def marks(extents, colour, top, h, tip):
            for off, ln in extents:
                mx = x0 + off / self.volume_size * w
                mw = max(2.0, ln / self.volume_size * w)
                r = QtCore.QRectF(mx, top, mw, h)
                g.fillRect(r, colour)
                self._hits.append((r.adjusted(-2, 0, 2, 0), tip + "\noffset %s, %s" % (size_text(off), size_text(ln)), None))

        ext = self.layout_data.get("extents") or []
        marks([(o, l) for k, o, l in ext if k == "mft"], QtGui.QColor(MFT_C), y + 5, 12, "$MFT")
        marks([(o, l) for k, o, l in ext if k == "usn"], QtGui.QColor(USN_C), y + 5, 12, "USN journal")
        for i, c in enumerate(self.copies):
            marks(c.get("extents") or [], _shade(i, n), y + 21, 12, "Shadow copy %s store" % _copy_name(c))
        if 0 <= self.selected < n:
            g.setPen(QtGui.QPen(QtGui.QColor(SEL_C), 1.5))
            g.setBrush(QtCore.Qt.NoBrush)
            for off, ln in self.copies[self.selected].get("extents") or []:
                mx = x0 + off / self.volume_size * w
                g.drawRect(QtCore.QRectF(mx - 1, y + 20, max(2.0, ln / self.volume_size * w) + 2, 14))
        self._edge(g, path)
        ly = y + 46
        lx = self._legend(g, x0, ly, MFT_C, "$MFT")
        lx = self._legend(g, lx, ly, USN_C, "USN journal")
        lx = self._legend(g, lx, ly, VSS_C, "each copy's store (older copies darker)")
        lx = self._legend(g, lx, ly, SEL_C, "the selected copy", "outline")
        lx = self._legend(g, lx, ly, USED_C, "used space")
        g.setFont(self.small_font)
        g.setPen(body)
        g.drawText(QtCore.QRectF(x0, ly, w, 17), QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter,
                   "%s of %s used" % (size_text(self.used), size_text(self.volume_size)))

        # 2. shadow storage: one segment per copy against what Windows allocated and its maximum
        y = 92
        vss_max = self.layout_data.get("vss_max") or 0
        alloc = self.layout_data.get("vss_allocated") or sum(c.get("store_bytes") or 0 for c in self.copies)
        used = self.layout_data.get("vss_used") or 0
        top = max(vss_max, alloc, used, 1)
        self._caption(g, y + 2, "Shadow storage", "%d cop%s" % (n, "y" if n == 1 else "ies"))
        gauge = QtCore.QRectF(x0, y, w, 28)
        path = self._track(g, gauge)
        g.setClipPath(path)
        gx = x0
        for i, c in enumerate(self.copies):
            sw = (c.get("store_bytes") or 0) / top * w
            r = QtCore.QRectF(gx, y, max(1.0, sw), 28)
            g.fillRect(r, _shade(i, n))
            if sw > 1.5:
                g.fillRect(QtCore.QRectF(gx + sw - 1, y, 1, 28), QtGui.QColor(TRACK_C))
            if 0 <= self.selected == i:
                g.setPen(QtGui.QPen(QtGui.QColor(SEL_C), 1.5))
                g.setBrush(QtCore.Qt.NoBrush)
                g.drawRect(r.adjusted(0.75, 0.75, -0.75, -0.75))
            self._hits.append((r, "Shadow copy %s: %s" % (_copy_name(c), size_text(c.get("store_bytes"))), i))
            gx += sw
        self._edge(g, path)
        if alloc:
            ax = x0 + alloc / top * w
            g.setPen(QtGui.QPen(QtGui.QColor(SEL_C), 1.2, QtCore.Qt.DashLine))
            g.drawLine(QtCore.QPointF(ax, y - 4), QtCore.QPointF(ax, y + 32))
        g.setFont(self.small_font)
        g.setPen(muted)
        share = (" - %d%% of the maximum" % round(100.0 * alloc / vss_max)) if vss_max and alloc else ""
        g.drawText(QtCore.QRectF(x0, y + 34, w, 17), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter,
                   "%s used  ·  %s allocated (dashed line)%s  ·  %s maximum (the whole bar)"
                   % (size_text(used), size_text(alloc), share,
                      size_text(vss_max) if vss_max else "no limit set"))

        # 3. the timeline: oldest copy to now, removals Windows logged, ticks in UTC
        y = 160
        self._caption(g, y + 2, "Timeline (UTC)", "oldest copy to now")
        times = [_utc(c.get("created")) for c in self.copies if _utc(c.get("created"))]
        now = datetime.datetime.utcnow()
        if not times:
            g.setFont(self.body_font)
            g.setPen(muted)
            g.drawText(QtCore.QRectF(x0, y, w, 64), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter | QtCore.Qt.TextWordWrap,
                       getattr(self, "empty_note", "") or "No shadow copies on this volume.")
            g.end()
            return
        # The axis runs from the oldest copy to now: older removals are counted, not drawn, or a
        # season of them squeezes every copy into the last pixel.
        t0 = min(times)
        t0 = t0 - (now - t0) * 0.04
        earlier = sum(1 for r in self.removals if _utc(r.get("at")) and _utc(r.get("at")) < t0)
        span = max(1.0, (now - t0).total_seconds())
        axis_y = y + 76

        def tx(t):
            return x0 + (t - t0).total_seconds() / span * w

        g.setPen(QtGui.QPen(QtGui.QColor(EDGE_C), 1.4))
        g.drawLine(QtCore.QPointF(x0, axis_y), QtCore.QPointF(x1, axis_y))
        step, fmt = next(((s, f) for s, f in _STEPS if span / s <= w / 96.0), _STEPS[-1])
        first = datetime.datetime.utcfromtimestamp((int((t0 - datetime.datetime(1970, 1, 1)).total_seconds())
                                                    // step + 1) * step)
        g.setFont(self.small_font)
        tick = first
        now_w = QtGui.QFontMetrics(self.cap_font, self).horizontalAdvance("NOW") + 8
        while tick < now:
            x = tx(tick)
            if x > x1 - now_w - 46:            # the "now" label owns the axis' right end
                break
            g.setPen(QtGui.QPen(QtGui.QColor(EDGE_C), 1))
            g.drawLine(QtCore.QPointF(x, axis_y + 3), QtCore.QPointF(x, axis_y + 8))
            g.setPen(muted)
            g.drawText(QtCore.QRectF(x - 50, axis_y + 9, 100, 16), QtCore.Qt.AlignCenter, tick.strftime(fmt))
            tick += datetime.timedelta(seconds=step)
        for r in self.removals:
            t = _utc(r.get("at"))
            if t is None or t < t0:
                continue
            x = tx(t)
            g.setPen(QtCore.Qt.NoPen)
            g.setBrush(QtGui.QColor(REMOVAL_C))
            g.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(x, axis_y - 4), QtCore.QPointF(x + 4, axis_y),
                                           QtCore.QPointF(x, axis_y + 4), QtCore.QPointF(x - 4, axis_y)]))
            self._hits.append((QtCore.QRectF(x - 5, axis_y - 5, 10, 10), "%s UTC  volsnap %s\n%s" % (
                r["at"].replace("T", " ").rstrip("Z"), r.get("event_id"), r.get("reason")), None))
        biggest = max([c.get("store_bytes") or 0 for c in self.copies] + [1])
        fm = QtGui.QFontMetrics(self.body_font, self)
        lanes_end = [-1e9, -1e9, -1e9]
        g.setFont(self.body_font)
        for i, c in enumerate(self.copies):
            t = _utc(c.get("created"))
            if t is None:
                continue
            x = tx(t)
            rad = 4.5 + 7 * ((c.get("store_bytes") or 0) / biggest) ** 0.5
            col = _shade(i, n)
            if c.get("exposed"):
                g.setPen(QtCore.Qt.NoPen)
                g.setBrush(col)
            else:
                g.setPen(QtGui.QPen(col, 1.8))
                g.setBrush(QtGui.QColor(TRACK_C))
            g.drawEllipse(QtCore.QPointF(x, axis_y), rad, rad)
            if i == self.selected:
                g.setPen(QtGui.QPen(QtGui.QColor(SEL_C), 1.5))
                g.setBrush(QtCore.Qt.NoBrush)
                g.drawEllipse(QtCore.QPointF(x, axis_y), rad + 4, rad + 4)
            name = _copy_name(c)
            tw = fm.horizontalAdvance(name)
            lane = next((k for k, end in enumerate(lanes_end) if x - tw / 2 > end + 10), None)
            if lane is not None:            # no room in any lane: the tooltip names it
                lanes_end[lane] = x + tw / 2
                ly = axis_y - 32 - lane * 18
                g.setPen(QtGui.QPen(QtGui.QColor(EDGE_C), 1))
                g.drawLine(QtCore.QPointF(x, ly + 17), QtCore.QPointF(x, axis_y - rad - 2))
                g.setPen(body if c.get("exposed") else muted)
                g.drawText(QtCore.QRectF(x - tw / 2 - 1, ly, tw + 2, 17), QtCore.Qt.AlignCenter, name)
            self._hits.append((QtCore.QRectF(x - rad - 3, axis_y - rad - 3, 2 * rad + 6, 2 * rad + 6),
                               "%s  %s UTC\n%s\n%s" % (name, (c.get("created") or "").replace("T", " ").rstrip("Z"),
                                                       size_text(c.get("store_bytes")), c.get("trigger") or ""), i))
        g.setPen(QtGui.QColor(NOW_C))
        g.setFont(self.cap_font)
        g.drawText(QtCore.QRectF(x1 - 60, axis_y + 9, 60, 16), QtCore.Qt.AlignRight, "now")
        g.setPen(QtGui.QPen(QtGui.QColor(NOW_C), 1.2, QtCore.Qt.DashLine))
        g.drawLine(QtCore.QPointF(x1, axis_y - 10), QtCore.QPointF(x1, axis_y + 6))
        ly = axis_y + 30
        lx = self._legend(g, x0, ly, VSS_C, "exposed by Windows", "dot")
        lx = self._legend(g, lx, ly, VSS_C, "in the catalog only (hidden)", "ring")
        lx = self._legend(g, lx, ly, REMOVAL_C, "a removal Windows logged", "diamond")
        lx = self._legend(g, lx, ly, NOW_C, "now")
        if earlier:
            g.setFont(self.small_font)
            g.setPen(muted)
            note = "%d earlier removal%s since %s, before the oldest copy: not drawn" % (
                earlier, "" if earlier == 1 else "s", min(r["at"] for r in self.removals)[:10])
            nw = QtGui.QFontMetrics(self.small_font, self).horizontalAdvance(note)
            if lx + nw > x1:                # no room beside the legend: the line below it
                g.drawText(QtCore.QRectF(x0, ly + 20, w, 17), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, note)
            else:
                g.drawText(QtCore.QRectF(x0, ly, w, 17), QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter, note)
        g.end()

    def mouseMoveEvent(self, event):
        for r, tip, _i in reversed(self._hits):
            if r.contains(QtCore.QPointF(event.pos())):
                QtWidgets.QToolTip.showText(event.globalPos(), tip, self)
                return
        QtWidgets.QToolTip.hideText()

    def mousePressEvent(self, event):
        for r, _tip, i in reversed(self._hits):
            if i is not None and r.contains(QtCore.QPointF(event.pos())):
                self.copy_clicked.emit(i)
                return


class ShadowCopiesDialog(QtWidgets.QDialog):
    """The Shadow Copies window."""

    def __init__(self, case_root: Optional[str] = None, parent=None, volume: str = None,
                 open_in_browser=None):
        super().__init__(parent)
        self.setWindowTitle("Shadow Copies")
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowMinMaxButtonsHint)
        if _theme is not None:
            _theme.fit_to_screen(self, 1500, 1260)
        else:
            self.resize(1480, 980)
        self.case_root = case_root
        self.copies: List[dict] = []
        self._worker = None
        self._prov_worker = None
        self._summary = ""
        self._run = None
        self._open_in_browser = open_in_browser
        if _theme is not None:
            _theme.begin_theme(self)
        self._build()
        if _theme is not None:
            _theme.apply_theme(self, clear_inline=False)
        try:
            from styles import CrowEyeStyles
            CrowEyeStyles.give_window_a_taskbar_button(self)
        except Exception:
            pass
        self._load(volume)

    # ---- layout ---------------------------------------------------------------------------
    def _card(self, caption, hint=None):
        if _theme is not None:
            return _theme.section_card(caption, hint)
        box = QtWidgets.QGroupBox(caption)
        v = QtWidgets.QVBoxLayout(box)
        head = QtWidgets.QHBoxLayout()
        if hint:
            head.addWidget(QtWidgets.QLabel(hint), 1)
        v.addLayout(head)
        return box, v, head

    def _variant(self, button, variant):
        if _theme is not None:
            _theme.set_variant(button, variant)
        return button

    def _build(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 14)
        root.setSpacing(12)

        top = QtWidgets.QHBoxLayout()
        top.setSpacing(12)
        titles = QtWidgets.QVBoxLayout()
        titles.setSpacing(4)
        title = QtWidgets.QLabel("Shadow Copies")
        sub = QtWidgets.QLabel(
            "Every shadow copy of the volume - exposed by Windows or only in its catalog - with the space it "
            "takes and where, what triggered it, the removals Windows logged, and what changed between the "
            "copies and now. Browse any copy in the File Browser, or recover files and apps from it.")
        sub.setWordWrap(True)
        if _theme is not None:
            _theme.set_role(title, "title")
            _theme.set_role(sub, "muted")
        titles.addWidget(title)
        titles.addWidget(sub)
        top.addLayout(titles, 1)
        if _theme is not None:
            self.help_btn, self.help_panel = _theme.how_it_works(HELP_HTML)
            top.addWidget(self.help_btn, 0, QtCore.Qt.AlignBottom)
        vol_label = QtWidgets.QLabel("Volume")
        if _theme is not None:
            _theme.set_role(vol_label, "label")
        self.volume_combo = QtWidgets.QComboBox()
        self.volume_combo.setMinimumWidth(96)
        self.refresh_btn = self._variant(QtWidgets.QPushButton("Refresh"), "ghost")
        self.browse_btn = self._variant(QtWidgets.QPushButton("Browse this copy"), "primary")
        self.browse_btn.setEnabled(False)
        self.browse_btn.setToolTip("Open the selected copy in the File Browser (or double-click its row)")
        for wdg in (vol_label, self.volume_combo, self.refresh_btn, self.browse_btn):
            top.addWidget(wdg, 0, QtCore.Qt.AlignBottom)
        root.addLayout(top)
        if _theme is not None:
            root.addWidget(self.help_panel)

        # Where they sit
        map_card, mv, _mh = self._card("Where they sit and what they take",
                                       "Hover a mark for its offset and size; click a copy to select it.")
        self.map = VolumeMap()
        from ui.loading_panel import LoadingPanel
        self.loading = LoadingPanel(
            "Reading this volume's shadow copies",
            "Windows' own list, the volume's VSS catalog (hidden copies too) and where each store sits on the "
            "disk. What made each copy is read next, from the event logs, without holding the window.",
            ["Asking Windows for its copies and shadow storage", "Reading the VSS catalog and each copy's store",
             "Laying out $MFT, the USN journal and the stores", "Reading the removals Windows logged"])
        self.map_stack = QtWidgets.QStackedWidget()
        self.map_stack.addWidget(self.loading)
        self.map_stack.addWidget(self.map)
        mv.addWidget(self.map_stack)

        # The copies, and what changed between them: two tabs, so each has the window's height
        tabs_card = _theme.set_card(_theme.Card()) if _theme is not None else QtWidgets.QFrame()
        tv = QtWidgets.QVBoxLayout(tabs_card)
        tv.setContentsMargins(16, 14, 16, 14)
        tv.setSpacing(10)
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setDocumentMode(True)
        tv.addWidget(self.tabs, 1)

        copies_page = QtWidgets.QWidget()
        cv = QtWidgets.QVBoxLayout(copies_page)
        cv.setContentsMargins(0, 6, 0, 0)
        cv.setSpacing(10)
        self.table = QtWidgets.QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["Copy", "Created (UTC)", "Age", "Size", "Exposed",
                                              "Triggered by", "Requester command line", "Shadow copy ID"])
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setMinimumHeight(34 * 3 + 44)      # the header and three copies, whatever the window
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(QtCore.Qt.ElideRight)
        hdr = self.table.horizontalHeader()
        hdr.setHighlightSections(False)
        hdr.setDefaultAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        for col in range(8):
            hdr.setSectionResizeMode(col, QtWidgets.QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(5, QtWidgets.QHeaderView.Stretch)
        self.why = QtWidgets.QTextBrowser()
        self.why.setOpenExternalLinks(False)
        self.why.setMinimumHeight(90)
        self.why.setHtml("<p style='color:#94a3b8'>Select a copy: what made it, and every record that says so, "
                         "is listed here.</p>")
        tsplit = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        tsplit.setChildrenCollapsible(False)
        tsplit.setHandleWidth(10)
        tsplit.addWidget(self.table)
        why_box = QtWidgets.QWidget()
        wv = QtWidgets.QVBoxLayout(why_box)
        wv.setContentsMargins(0, 0, 0, 0)
        wv.setSpacing(6)
        why_label = QtWidgets.QLabel("Why this copy exists")
        if _theme is not None:
            _theme.set_role(why_label, "caption")
        wv.addWidget(why_label)
        wv.addWidget(self.why, 1)
        tsplit.addWidget(why_box)
        tsplit.setStretchFactor(0, 3)
        tsplit.setStretchFactor(1, 2)
        cv.addWidget(tsplit, 1)
        crow = QtWidgets.QHBoxLayout()
        crow.setSpacing(12)
        cmp_label = QtWidgets.QLabel("Compare the ticked copies with now:")
        if _theme is not None:
            _theme.set_role(cmp_label, "label")
        self.whole_radio = QtWidgets.QRadioButton("The whole volume")
        self.folder_radio = QtWidgets.QRadioButton("One folder:")
        self.whole_radio.setChecked(True)
        self.scope_edit = QtWidgets.QLineEdit()
        self.scope_edit.setPlaceholderText("e.g. Users\\name\\Documents")
        self.scope_edit.setMinimumWidth(320)
        self.scope_edit.setEnabled(False)
        self.compare_btn = self._variant(QtWidgets.QPushButton("Compare"), "primary")
        self.compare_btn.setToolTip("Read each ticked copy's $MFT and now's in step, and count what changed")
        self.cancel_btn = self._variant(QtWidgets.QPushButton("Cancel"), "ghost")
        self.cancel_btn.hide()
        for wdg in (cmp_label, self.whole_radio, self.folder_radio, self.scope_edit):
            crow.addWidget(wdg)
        crow.addStretch(1)
        crow.addWidget(self.cancel_btn)
        crow.addWidget(self.compare_btn)
        cv.addLayout(crow)
        self.tabs.addTab(copies_page, "The copies")

        changes_page = QtWidgets.QWidget()
        kv = QtWidgets.QVBoxLayout(changes_page)
        kv.setContentsMargins(0, 6, 0, 0)
        kv.setSpacing(10)
        self.progress = QtWidgets.QProgressBar()
        self.progress.setMaximumHeight(6)
        self.progress.setTextVisible(False)
        self.progress.hide()
        kv.addWidget(self.progress)
        self.results = QtWidgets.QStackedWidget()
        hint = QtWidgets.QLabel(
            "Nothing compared yet. On The copies, tick the copies to compare, choose the whole volume or one "
            "folder, and press Compare. Each state's $MFT is read in step - minutes for a whole volume, not a walk "
            "of every file - and each folder's size in every state shows here with its added / deleted / changed "
            "counts, and the files that changed below it.")
        hint.setWordWrap(True)
        hint.setAlignment(QtCore.Qt.AlignCenter)
        hint.setMargin(40)
        if _theme is not None:
            _theme.set_role(hint, "muted")
        self.results.addWidget(hint)
        res = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        res.setChildrenCollapsible(False)
        res.setHandleWidth(10)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setHeaderLabels(["Folder", "Size in each state"])
        files_box = QtWidgets.QWidget()
        fv = QtWidgets.QVBoxLayout(files_box)
        fv.setContentsMargins(0, 0, 0, 0)
        fv.setSpacing(8)
        frow = QtWidgets.QHBoxLayout()
        files_label = QtWidgets.QLabel("Files changed below the selected folder, in")
        if _theme is not None:
            _theme.set_role(files_label, "label")
        frow.addWidget(files_label)
        self.interval_combo = QtWidgets.QComboBox()
        self.interval_combo.setMinimumWidth(360)
        frow.addWidget(self.interval_combo)
        frow.addStretch(1)
        # Recover the selected files into the case: a deleted file from the
        # state before it was deleted, an added or changed one from the state
        # after (Ghassan, 2026-11-01).
        self.recover_btn = self._variant(QtWidgets.QPushButton("Recover selected into the case"),
                                         "primary")
        self.recover_btn.setToolTip("A deleted file is taken from the copy it was still in; an added or "
                                    "changed file from the newer state. Copied into the case with its "
                                    "SHA-256 and a chain-of-custody record.")
        self.recover_btn.setEnabled(False)
        self.recover_btn.clicked.connect(self._recover_files)
        frow.addWidget(self.recover_btn)
        fv.addLayout(frow)
        self.files = QtWidgets.QTableWidget(0, 6)
        self.files.setHorizontalHeaderLabels(["Change", "Path", "Size before", "Size after",
                                              "Modified before (UTC)", "Modified after (UTC)"])
        self.files.verticalHeader().hide()
        self.files.verticalHeader().setDefaultSectionSize(30)
        self.files.setShowGrid(False)
        self.files.setWordWrap(False)
        self.files.setTextElideMode(QtCore.Qt.ElideMiddle)
        self.files.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.files.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.files.setAlternatingRowColors(True)
        fh = self.files.horizontalHeader()
        fh.setHighlightSections(False)
        fh.setDefaultAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        for col in (0, 2, 3, 4, 5):
            fh.setSectionResizeMode(col, QtWidgets.QHeaderView.ResizeToContents)
        fh.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        self.files.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.files.customContextMenuRequested.connect(self._files_menu)
        self.files.itemSelectionChanged.connect(
            lambda: self.recover_btn.setEnabled(bool(self.files.selectionModel().selectedRows())
                                                and self._run is not None))
        fv.addWidget(self.files, 1)
        res.addWidget(self.tree)
        res.addWidget(files_box)
        res.setStretchFactor(0, 1)
        res.setStretchFactor(1, 1)
        self.results.addWidget(res)
        kv.addWidget(self.results, 1)
        self.tabs.addTab(changes_page, "What changed")

        split = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(10)
        split.addWidget(map_card)
        split.addWidget(tabs_card)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        root.addWidget(split, 1)

        self.status = QtWidgets.QLabel("Reading the shadow copies...")
        if _theme is not None:
            _theme.set_role(self.status, "muted")
        root.addWidget(self.status)

        self.refresh_btn.clicked.connect(lambda: self._load(self.volume_combo.currentData(), fresh=True))
        self.volume_combo.activated.connect(lambda *_: self._load(self.volume_combo.currentData()))
        self.folder_radio.toggled.connect(self.scope_edit.setEnabled)
        self.table.itemSelectionChanged.connect(self._selected)
        self.map.copy_clicked.connect(lambda i: self.table.selectRow(i))
        self.browse_btn.clicked.connect(self._browse)
        self.table.cellDoubleClicked.connect(lambda *_: self._browse())
        self.compare_btn.clicked.connect(self._compare)
        self.cancel_btn.clicked.connect(self._cancel)
        self.tree.itemExpanded.connect(self._expand)
        self.tree.itemSelectionChanged.connect(self._fill_files)
        self.interval_combo.currentIndexChanged.connect(lambda *_: self._fill_files())

    def set_case(self, case_root):
        """The case a comparison is saved into (Target_Artifacts/shadow_copies.db)."""
        self.case_root = case_root

    # ---- loading --------------------------------------------------------------------------
    def _load(self, volume=None, fresh=False):
        """Phase 1: the copies, their sizes and places - the map, the gauge, the timeline and the table
        (about a second; reused for a minute, `fresh` reads again). Phase 2 (_load_provenance) then reads
        what made each copy from the event logs and fills it in."""
        from ui.app_acquisition_dialog import _Worker
        from ui.loading_panel import step
        if self._worker is not None:
            return
        max_age = 0 if fresh else None
        self.loading.restart(steps=["Asking Windows for its copies and shadow storage",
                                    "Reading the VSS catalog and each copy's store",
                                    "Laying out $MFT, the USN journal and the stores",
                                    "Reading the removals Windows logged"])
        self.map_stack.setCurrentIndex(0)
        self.status.setText("Reading the shadow copies...")
        self.refresh_btn.setEnabled(False)

        def work(report):
            import shutil
            from Artifacts_Collectors import shadow_copies as sc, volume_layout as vl
            step(report, "Asking Windows for its copies and shadow storage")
            snap = sc.snapshot(provenance=False, max_age=max_age)
            storage = vl.shadow_storage(snapshot=snap)
            letters = sorted(storage) or ["C"]
            letter = (volume or (letters[0] if letters else "C")).rstrip(":\\").upper()
            step(report, "Reading the VSS catalog and each copy's store")
            copies = sc.live_copies(letter, provenance=False, max_age=max_age)
            step(report, "Laying out $MFT, the USN journal and the stores")
            lay = vl.volume_layout(letter, storage)
            step(report, "Reading the removals Windows logged")
            removed = sc.removals(letter, rows=snap.get("removals"))
            du = shutil.disk_usage("%s:\\" % letter)
            report("", 1, 1)
            return {"letters": letters, "letter": letter, "copies": copies, "layout": lay,
                    "removals": removed, "size": du.total, "used": du.used, "max_age": max_age,
                    "storage": storage.get(letter) or {}}
        self._worker = _Worker(work, self)
        self._worker.progress.connect(self.loading.report)
        self._worker.finished_ok.connect(self._loaded)
        self._worker.failed.connect(self._load_failed)
        self._worker.start()

    def _load_failed(self, message):
        self._worker = None
        self.refresh_btn.setEnabled(True)
        self.loading.fail(message)
        self.status.setText("The shadow copies could not be read: " + message)

    def _load_provenance(self, letter, max_age):
        """Phase 2: what made each copy - restore points, VSS 8231, System Restore 8194 / 8300, the VSS
        diagnostics key, store flags - read without holding the window, then put in place."""
        from ui.app_acquisition_dialog import _Worker

        def work(report):
            from Artifacts_Collectors import shadow_copies as sc
            return sc.live_copies(letter, provenance=True, max_age=max_age)

        def done(full):
            self._prov_worker = None
            by_id = {c.get("shadow_id"): c for c in full}
            for r, c in enumerate(self.copies):
                f = by_id.get(c.get("shadow_id"))
                if f is None:
                    continue
                c.update(provenance=f.get("provenance"), trigger=f.get("trigger"), requester=f.get("requester"),
                         restore_point=f.get("restore_point"))
                req = c.get("requester") or {}
                for col, val in ((5, c.get("trigger") or ""), (6, req.get("command_line", ""))):
                    it = self.table.item(r, col)
                    if it is not None:
                        it.setText(val)
                        it.setForeground(QtGui.QColor("#E2E8F0" if c.get("exposed") else "#94A3B8"))
                        if col == 6 and req.get("callers"):
                            it.setToolTip("Caller stack: " + " <- ".join(req["callers"]))
            self._selected()
            self.status.setText(self._summary)

        def failed(message):
            self._prov_worker = None
            self.status.setText(self._summary + "  What made each copy could not be read: " + message)
        self._prov_worker = _Worker(work, self)
        self._prov_worker.finished_ok.connect(done)
        self._prov_worker.failed.connect(failed)
        self._prov_worker.start()

    def _loaded(self, data):
        self._worker = None
        self.refresh_btn.setEnabled(True)
        self.loading.finish()
        self.map_stack.setCurrentIndex(1)
        self.copies = data["copies"]
        self.volume_combo.blockSignals(True)
        self.volume_combo.clear()
        for l in data["letters"]:
            self.volume_combo.addItem("%s:" % l, l)
        self.volume_combo.setCurrentIndex(max(0, self.volume_combo.findData(data["letter"])))
        self.volume_combo.blockSignals(False)
        self.map.set_data(self.copies, data["layout"], data["removals"], data["size"], data["used"])
        empty_note = ""
        if not self.copies:
            from Artifacts_Collectors import shadow_copies as sc
            empty_note = sc.explain_no_copies(data["letter"], data["removals"], data.get("storage"),
                                              data["size"], data["used"])
        self.map.set_empty_note(empty_note)
        self.table.setRowCount(len(self.copies))
        for r, c in enumerate(self.copies):
            req = c.get("requester") or {}
            cells = [_copy_name(c), (c.get("created") or "").replace("T", " ").rstrip("Z"), _age(c.get("created")),
                     size_text(c.get("store_bytes")), "exposed" if c.get("exposed") else "catalog only",
                     c.get("trigger") or "", req.get("command_line", ""), c.get("shadow_id") or ""]
            for col, val in enumerate(cells):
                it = QtWidgets.QTableWidgetItem(val)
                if col == 0:
                    it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
                    it.setCheckState(QtCore.Qt.Checked if r >= len(self.copies) - 3 else QtCore.Qt.Unchecked)
                if col == 6 and req.get("callers"):
                    it.setToolTip("Caller stack: " + " <- ".join(req["callers"]))
                if not c.get("exposed"):
                    it.setForeground(QtGui.QColor("#94A3B8"))
                if col == 5 and c.get("provenance") is None:
                    it.setForeground(QtGui.QColor("#64748B"))
                self.table.setItem(r, col, it)
        # The tick box is wider under the theme than the header's measure of the column allows.
        fm = self.table.fontMetrics()
        self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Interactive)
        self.table.setColumnWidth(0, max([fm.horizontalAdvance(_copy_name(c)) for c in self.copies] + [40]) + 64)
        hidden = sum(1 for c in self.copies if not c.get("exposed"))
        self._summary = ("%d shadow cop%s of %s: (%d exposed by Windows, %d in the catalog only); "
                         "%d removal(s) logged by Windows." % (
                             len(self.copies), "y" if len(self.copies) == 1 else "ies", data["letter"],
                             len(self.copies) - hidden, hidden, len(data["removals"])))
        if empty_note:
            self._summary = empty_note
        if self.copies:
            self.table.selectRow(len(self.copies) - 1)
        if any(c.get("provenance") is None for c in self.copies):
            self.status.setText(self._summary + "  Reading what made each copy...")
            self._load_provenance(data["letter"], data.get("max_age"))
        else:
            self.status.setText(self._summary)

    def _selected(self):
        rows = self.table.selectionModel().selectedRows()
        i = rows[0].row() if rows else -1
        self.map.select(i)
        self.browse_btn.setEnabled(i >= 0)
        if 0 <= i < len(self.copies):
            self.why.setHtml(_why_html(self.copies[i]))

    def _browse(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        c = self.copies[rows[0].row()]
        if self._open_in_browser is not None:
            self._open_in_browser(c)
            return
        from ui.file_browser_dialog import FileBrowserDialog
        dlg = FileBrowserDialog(self.case_root, self.parent())
        dlg.show()
        dlg.open_shadow_copy(c)

    # ---- comparison -----------------------------------------------------------------------
    def _ticked(self):
        return [i for i in range(self.table.rowCount())
                if self.table.item(i, 0) and self.table.item(i, 0).checkState() == QtCore.Qt.Checked]

    def _compare(self):
        from ui.app_acquisition_dialog import _Worker
        picks = self._ticked()
        if not picks:
            self.status.setText("Tick at least one copy in the first column to compare.")
            return
        letter = self.volume_combo.currentData() or "C"
        specs = []
        for i in picks:
            c = self.copies[i]
            specs.append({"kind": "device" if c.get("exposed") else "hidden", "volume": letter,
                          "shadow_id": c.get("shadow_id"), "label": _copy_name(c)})
        specs.append({"kind": "live", "volume": letter, "label": "now"})
        # The copy behind each state, kept for recovering its files later.
        self._state_copies = [self.copies[i] for i in picks] + [None]
        scope = self.scope_edit.text().strip() if self.folder_radio.isChecked() else ""
        case = self.case_root
        worker = None

        def work(report):
            from Artifacts_Collectors.shadow_compare import compare
            return compare(specs, scope=scope, case_dir=case, volume=letter, progress=report,
                           is_cancelled=lambda: bool(worker is not None and worker.cancelled))
        worker = _Worker(work, self)
        self._worker = worker
        self.compare_btn.setEnabled(False)
        self.cancel_btn.show()
        self.progress.show()
        self.progress.setRange(0, 0)
        self.tabs.setCurrentIndex(1)

        def prog(msg, done, total):
            self.status.setText(msg)
            if total:
                self.progress.setRange(0, total)
                self.progress.setValue(done)
        worker.progress.connect(prog)
        worker.finished_ok.connect(self._compared)
        worker.failed.connect(self._compare_failed)
        worker.start()
        self.status.setText("Reading the $MFT of %d state(s) in step..." % len(specs))

    def _compare_failed(self, msg):
        self._worker = None
        self.compare_btn.setEnabled(True)
        self.cancel_btn.hide()
        self.progress.hide()
        self.status.setText("The comparison failed: " + msg)

    def _cancel(self):
        if self._worker is not None:
            self._worker.cancelled = True

    def _compared(self, result):
        self._worker = None
        self.compare_btn.setEnabled(True)
        self.cancel_btn.hide()
        self.progress.hide()
        self._run = result
        self.results.setCurrentIndex(1)
        self.tabs.setCurrentIndex(1)
        states = result["states"]
        self.interval_combo.blockSignals(True)
        self.interval_combo.clear()
        for k in range(len(states) - 1):
            a = result["intervals"][k] if k < len(result["intervals"]) else [0, 0, 0]
            self.interval_combo.addItem("%s -> %s  (+%d  -%d  ~%d)" % (states[k], states[k + 1], a[0], a[1], a[2]), k)
        self.interval_combo.blockSignals(False)
        cols = ["Folder"] + ["Size at %s" % s for s in states] + ["%s -> %s" % (states[k], states[k + 1])
                                                                  for k in range(len(states) - 1)]
        self.tree.clear()
        self.tree.setColumnCount(len(cols))
        self.tree.setHeaderLabels(cols)
        con = sqlite3.connect(result["database"])
        self._con = con
        scope = (self.scope_edit.text().strip().strip("\\") if self.folder_radio.isChecked() else "")
        top = self._folder_item(scope or "", scope or "%s: (whole volume)" % (self.volume_combo.currentData() or ""))
        self.tree.addTopLevelItem(top)
        top.setExpanded(True)
        for col in range(1, len(cols)):
            self.tree.header().setSectionResizeMode(col, QtWidgets.QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        what = "Stopped early - partial counts" if result.get("cancelled") else "Compared"
        self.status.setText("%s %s; %d changed file row(s) kept. Saved in %s." % (
            what, ", ".join(states), result["files"], result["database"]))
        self._fill_files()

    # ---- recovering a changed file ---------------------------------------------------------
    def _state_source(self, k):
        """The source for state ``k`` of the comparison: a shadow copy (exposed or rebuilt
        from the catalog) or, for "now", the live volume."""
        from Artifacts_Collectors.app_acquisition.sources import LiveSource, ShadowSource
        copies = getattr(self, "_state_copies", None) or []
        copy = copies[k] if 0 <= k < len(copies) else None
        if copy is None:
            return LiveSource((self.volume_combo.currentData() or "C") + ":")
        return ShadowSource(dict(copy, volume=copy.get("volume") or self.volume_combo.currentData() or "C"))

    def _selected_changes(self):
        """[(change, path, state index to read)] of the selected rows."""
        k = self.interval_combo.currentData() or 0
        out = []
        for idx in self.files.selectionModel().selectedRows():
            change = self.files.item(idx.row(), 0).text()
            path = self.files.item(idx.row(), 1).text().strip("\\")
            out.append((change, path, k if change == "deleted" else k + 1))
        return out

    def _files_menu(self, pos):
        if self._run is None or not self.files.selectionModel().selectedRows():
            return
        picks = self._selected_changes()
        menu = QtWidgets.QMenu(self)
        what = ("\"%s\"" % picks[0][1].rsplit("\\", 1)[-1]) if len(picks) == 1 else "%d files" % len(picks)
        states = self._run["states"]
        if len(picks) == 1:
            menu.addAction("Recover %s into the case (from %s)" % (what, states[picks[0][2]])).triggered.connect(
                self._recover_files)
            menu.addAction("Open in the File Browser at %s" % states[picks[0][2]]).triggered.connect(
                lambda: self._open_at(picks[0]))
        else:
            menu.addAction("Recover %s into the case" % what).triggered.connect(self._recover_files)
        menu.addAction("Copy path" + ("s" if len(picks) > 1 else "")).triggered.connect(
            lambda: QtWidgets.QApplication.clipboard().setText("\n".join(p for _c, p, _k in picks)))
        menu.exec_(self.files.viewport().mapToGlobal(pos))

    def _open_at(self, pick):
        _change, path, k = pick
        copies = getattr(self, "_state_copies", None) or []
        copy = copies[k] if 0 <= k < len(copies) else None
        from ui.file_browser_dialog import FileBrowserDialog
        dlg = FileBrowserDialog(self.case_root, self.parent())
        dlg.show()
        if copy is not None:
            dlg.open_shadow_copy(copy)
        folder = path.rsplit("\\", 1)[0] if "\\" in path else ""
        QtCore.QTimer.singleShot(1500, lambda: dlg.browser.open(folder))

    def _recover_files(self):
        """The selected changed files, copied into the case from the state that holds them -
        the same collection as the File Browser's (hash, custody, manifest)."""
        if self._run is None:
            return
        if not self.case_root:
            self.status.setText("Open a case first: recovered files are saved into the case.")
            return
        picks = self._selected_changes()
        if not picks:
            return
        from ui.app_acquisition_dialog import _Worker
        states = self._run["states"]
        by_state = {}
        for _change, path, k in picks:
            by_state.setdefault(k, []).append(path)
        case = self.case_root
        worker = None

        def work(report):
            from Artifacts_Collectors.app_acquisition.catalog import AppEntry
            from Artifacts_Collectors.app_acquisition.collector import acquire
            from Artifacts_Collectors.app_acquisition.footprint import Footprint, FootprintItem, _user_of
            results = []
            for k, paths in sorted(by_state.items()):
                if worker is not None and worker.cancelled:
                    break
                source = self._state_source(k)
                try:
                    fp = Footprint(AppEntry(name="Recovered from %s" % states[k], sources=["Shadow Copies"]))
                    for p in paths:
                        fp.add(FootprintItem("file", p, "changed between shadow copies (Shadow Copies, "
                                             "What changed)", _user_of(p)))
                    results.append((states[k], acquire(
                        fp, source, case, progress=report, record_kind="file collection",
                        is_cancelled=lambda: bool(worker is not None and worker.cancelled))))
                finally:
                    try:
                        source.close()
                    except Exception:
                        pass
            return results
        worker = _Worker(work, self)
        self._recover_worker = worker
        self.recover_btn.setEnabled(False)
        self.progress.show()
        self.progress.setRange(0, 0)

        def prog(msg, done, total):
            self.status.setText(msg)
            if total:
                self.progress.setRange(0, total)
                self.progress.setValue(done)

        def done(results):
            self._recover_worker = None
            self.progress.hide()
            self.recover_btn.setEnabled(True)
            files = sum(r.files for _s, r in results)
            failed = sum(r.failed for _s, r in results)
            msg = "Recovered %d file(s) into the case from %s" % (files, ", ".join(s for s, _r in results))
            if failed:
                errs = [e for _s, r in results for e in r.errors]
                msg += "; %d could not be read%s" % (failed, (": " + errs[0]) if errs else "")
            folders = [r.folder for _s, r in results if r.folder]
            if folders:
                msg += ". Saved in %s" % folders[0]
            self.status.setText(msg)

        def failed(message):
            self._recover_worker = None
            self.progress.hide()
            self.recover_btn.setEnabled(True)
            self.status.setText("Not recovered: %s" % message)
        worker.progress.connect(prog)
        worker.finished_ok.connect(done)
        worker.failed.connect(failed)
        worker.start()

    def _folder_item(self, path, title=None):
        rid = self._run["run_id"]
        n = len(self._run["states"])
        item = QtWidgets.QTreeWidgetItem([title or path.rsplit("\\", 1)[-1]])
        item.setData(0, QtCore.Qt.UserRole, path)
        sizes = dict(self._con.execute("SELECT state, size_bytes || ' ' || files FROM shadow_compare_folders "
                                       "WHERE run_id=? AND path=?", (rid, path)).fetchall())
        for k in range(n):
            v = sizes.get(k)
            if v:
                b, f = v.split(" ")
                item.setText(1 + k, "%s (%s files)" % (size_text(int(b)), f))
                item.setTextAlignment(1 + k, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        ch = {r[0]: r[1:] for r in self._con.execute(
            "SELECT interval, added, deleted, changed FROM shadow_compare_folder_changes WHERE run_id=? AND path=?",
            (rid, path))}
        for k in range(n - 1):
            a = ch.get(k)
            if a and any(a):
                item.setText(1 + n + k, "+%d  -%d  ~%d" % a)
                item.setForeground(1 + n + k, QtGui.QColor("#FACC15"))
        item.addChild(QtWidgets.QTreeWidgetItem(["..."]))
        return item

    def _expand(self, item):
        if item.data(0, QtCore.Qt.UserRole + 1):
            return
        item.setData(0, QtCore.Qt.UserRole + 1, True)
        item.takeChildren()
        path = item.data(0, QtCore.Qt.UserRole) or ""
        rid = self._run["run_id"]
        depth = (path.count("\\") + 1) if path else 0
        like = (path + "\\%") if path else "%"
        rows = self._con.execute(
            "SELECT path, MAX(size_bytes) FROM shadow_compare_folders WHERE run_id=? AND depth=? AND path LIKE ? "
            "GROUP BY path ORDER BY MAX(size_bytes) DESC LIMIT 2000", (rid, depth + 1, like)).fetchall()
        for p, _s in rows:
            item.addChild(self._folder_item(p))

    def _fill_files(self):
        if not self._run:
            return
        items = self.tree.selectedItems()
        path = items[0].data(0, QtCore.Qt.UserRole) if items else ""
        k = self.interval_combo.currentData() or 0
        like = (path + "\\%") if path else "%"
        rows = self._con.execute(
            "SELECT change, path, size_before, size_after, modified_before, modified_after FROM shadow_compare_files "
            "WHERE run_id=? AND interval=? AND path LIKE ? ORDER BY path LIMIT 5000",
            (self._run["run_id"], k, like)).fetchall()
        self.files.setRowCount(len(rows))
        colour = {"added": "#34D399", "deleted": "#FBBF24", "changed": "#22D3EE", "replaced": "#22D3EE"}
        for r, row in enumerate(rows):
            vals = [row[0], row[1], size_text(row[2]) if row[2] is not None else "",
                    size_text(row[3]) if row[3] is not None else "",
                    (row[4] or "").replace("T", " ").rstrip("Z"), (row[5] or "").replace("T", " ").rstrip("Z")]
            for c, v in enumerate(vals):
                it = QtWidgets.QTableWidgetItem(v)
                if c == 0:
                    it.setForeground(QtGui.QColor(colour.get(row[0], "#E2E8F0")))
                self.files.setItem(r, c, it)
        self.files.resizeColumnToContents(0)

    def closeEvent(self, event):
        rec = getattr(self, "_recover_worker", None)
        if rec is not None and rec.isRunning():
            rec.cancelled = True
            rec.wait(60000)
        prov = getattr(self, "_prov_worker", None)
        if prov is not None and prov.isRunning():
            prov.wait(15000)
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancelled = True
            self._worker.wait(10000)
        super().closeEvent(event)
