"""
Partition and Volume Analysis Window for Crow Eye
=================================================

This module provides a modern cyberpunk-themed UI window for displaying
disk partition and volume information. It features:
- Visual partition layout representation
- Detailed partition information table
- Color-coded partition types (boot, system, swap, Linux)
- Neon glow effects and dark theme aesthetics

Author: Ghassan Elsman (Crow Eye Team)
License: GPL-3.0
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QLabel, QFrame, QScrollArea, QWidget, QPushButton, QProgressBar,
    QHeaderView, QSizePolicy
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QRectF, QPointF
from PyQt5.QtGui import QFont, QColor, QPalette, QPainter, QPen, QBrush, QFontMetrics
from PyQt5.QtWidgets import QToolTip
import sys
import os

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Artifacts_Collectors.partition_analyzer import PartitionAnalyzer, PartitionInfo, DiskInfo


class PartitionLoadWorker(QThread):
    """Worker thread to load partition data without blocking the UI"""
    finished = pyqtSignal(list)
    error = pyqtSignal(str)
    status = pyqtSignal(str)

    def __init__(self, db_paths=None, partitions_json=None, force_refresh=False):
        super().__init__()
        self.db_paths = self._normalize_db_paths(db_paths)
        self.partitions_json = partitions_json
        self.force_refresh = force_refresh

    def _normalize_db_paths(self, db_paths):
        if db_paths is None:
            return []
        if isinstance(db_paths, str):
            return [('Current System', db_paths)]
        if isinstance(db_paths, list):
            if len(db_paths) > 0 and isinstance(db_paths[0], tuple):
                return db_paths
            return [(f'Source {i+1}', path) for i, path in enumerate(db_paths)]
        return []

    def run(self):
        # No COM on this thread, on purpose: WMI is then unavailable here and the analyzer reads the
        # disks through Get-Disk / Get-Partition, which list every partition. WMI's Win32_DiskPartition
        # does not list the Microsoft Reserved partition, so the window would lose it. The Storage
        # queries come from one shared PowerShell process (PartitionAnalyzer._ps), so this path is the
        # fast one too.
        self._run()

    def _run(self):
        try:
            self.status.emit("Reading the disks and their partitions")
            analyzer = PartitionAnalyzer()
            all_disks = []

            if self.partitions_json and os.path.exists(self.partitions_json) and not self.force_refresh:
                self.status.emit("Loading partition data from partitions.json...")
                try:
                    disks = analyzer.load_from_json(self.partitions_json)
                    if disks:
                        for disk in disks:
                            disk.source = "Offline JSON"
                        all_disks.extend(disks)
                        self.status.emit(f"Loaded {len(all_disks)} disk(s) from JSON")
                        self.finished.emit(all_disks)
                        return
                except Exception as e:
                    self.status.emit(f"Could not load from partitions.json: {e}")

            if self.db_paths and not self.force_refresh:
                for source_name, db_path in self.db_paths:
                    if os.path.exists(db_path):
                        self.status.emit(f"Loading partition data from {source_name}...")
                        disks = analyzer.load_from_database(db_path)
                        if disks:
                            for disk in disks:
                                disk.source = source_name
                            all_disks.extend(disks)
                if all_disks:
                    self.status.emit(f"Loaded {len(all_disks)} disk(s) from {len(self.db_paths)} source(s)")
                    self.finished.emit(all_disks)
                    return

            self.status.emit("Reading every partition, its file system, $MFT, USN journal and shadow storage")
            disks = analyzer.get_disks_with_partitions()
            for disk in disks:
                disk.source = "Current System"
            
            if self.db_paths:
                source_name, db_path = self.db_paths[0]
                db_dir = os.path.dirname(db_path)
                if db_dir and not os.path.exists(db_dir):
                    os.makedirs(db_dir, exist_ok=True)
                self.status.emit("Saving the analysis with the case")
                analyzer.save_to_database(db_path, disks)

            self.status.emit("Analysis complete")
            self.finished.emit(disks)
        except Exception as e:
            self.error.emit(str(e))


# The volume's own structures, one colour each, used nowhere else on this window.
LAYOUT_KINDS = (
    ('mft', '$MFT', '#F472B6'),
    ('usn', 'USN journal', '#A3E635'),
    ('vss', 'Shadow storage', '#FACC15'),
)


class PartitionBar(QWidget):
    """A disk drawn to scale, with each NTFS volume's $MFT, USN journal and shadow-copy
    storage at their real positions inside it.

    On that scale the structures are slivers - a 3 GB $MFT is a third of a percent of a 1 TB
    disk - and so are the EFI and MSR partitions, so nothing small carries its text inside
    itself: its label sits in a lane above or below the bar, joined to it by a leader line.
    A segment or marker is never drawn narrower than a few pixels, so it can always be seen
    and pointed at; the tooltip gives its exact offset and size.
    """

    BAR_H = 52
    LANE_H = 20
    VSS_LANE_H = 34
    # Every partition is at least this wide, so a 16 MB MSR or a 260 MB EFI partition is a segment
    # with its name and size in it, not a sliver; the large ones share what is left in proportion.
    # The structures inside a partition ($MFT, USN, shadow storage) stay at their real positions
    # within it, so the bar is to scale inside each partition, not across small ones.
    MIN_SEG = 96
    MIN_MARK = 2
    PAD = 8

    def __init__(self, disk, analyzer, color_fn, parent=None):
        super().__init__(parent)
        self.disk = disk
        self.analyzer = analyzer
        self.color_fn = color_fn
        self.parts = sorted(disk.partitions, key=lambda p: p.partition_index)
        self.font = _font(12)
        self.bold = _font(13, True)
        self.selected = None
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._hits = []
        self._lanes = (0, 0)
        self.setMinimumHeight(self.BAR_H + 2 * self.PAD)
        self.setStyleSheet("background: transparent; border: none;")

    @staticmethod
    def _name(p):
        """'C:', or what the partition is for when it has no letter: 'EFI', 'Recovery', 'MSR'."""
        if p.mountpoint:
            return p.mountpoint.rstrip('\\')
        role = partition_role(p)
        if role in ('efi', 'msr', 'recovery', 'linux', 'swap'):
            return {'efi': 'EFI', 'msr': 'MSR', 'recovery': 'Recovery', 'linux': 'Linux', 'swap': 'Swap'}[role]
        kind = str(p.partition_type).lower()
        for key, short in (('efi', 'EFI'), ('recovery', 'Recovery'), ('reserved', 'MSR'), ('msr', 'MSR'),
                           ('swap', 'Swap'), ('linux', 'Linux')):
            if key in kind:
                return short
        return p.volume_label or 'Partition %d' % p.partition_index

    # ---- layout ----------------------------------------------------------------------
    def _segments(self, x0, width):
        """(partition, x, w): proportional, every segment at least MIN_SEG wide."""
        n = len(self.parts)
        if not n:
            return []
        gap = 2
        avail = max(1, width - gap * (n - 1))
        sizes = [max(0, p.total_size) for p in self.parts]
        total = sum(sizes) or n
        raw = [avail * (sz / total if sum(sizes) else 1.0 / n) for sz in sizes]
        small = [r < self.MIN_SEG for r in raw]
        big_total = sum(r for r, sm in zip(raw, small) if not sm) or 1
        spare = avail - self.MIN_SEG * sum(small)
        widths = [self.MIN_SEG if sm else r * spare / big_total for r, sm in zip(raw, small)]
        out, x = [], x0
        for p, w in zip(self.parts, widths):
            out.append((p, x, w))
            x += w + gap
        return out

    def _labels(self, x0, x1):
        """Every label as dict(text, anchor, side, kind, part, meter), placed in lanes."""
        fm = QFontMetrics(self.font, self)
        labels = []
        fb = QFontMetrics(self.bold, self)
        for p, sx, sw in self._segments(x0, x1 - x0):
            text = '%s  %s' % (self._name(p), self.analyzer.format_size(p.total_size))
            inside = max(fb.horizontalAdvance(self._name(p)), fm.horizontalAdvance(
                self.analyzer.format_size(p.total_size)))
            if inside + 12 > sw:
                labels.append({'text': text, 'anchor': sx + sw / 2, 'side': 'below', 'kind': None, 'part': p})
            total = max(1, p.total_size)
            for kind, title, _colour in LAYOUT_KINDS:
                ext = [e for e in (p.extents or []) if e[0] == kind]
                if not ext:
                    continue
                biggest = max(ext, key=lambda e: e[2])
                anchor = sx + (biggest[1] + biggest[2] / 2) / total * sw
                if kind == 'mft':
                    text = '%s  %s  (%d runs)' % (title, self.analyzer.format_size(p.mft_bytes), len(ext))
                elif kind == 'usn':
                    text = '%s  %s' % (title, self.analyzer.format_size(p.usn_bytes))
                else:
                    text = '%s  %s used of %s max  -  %d cop%s' % (
                        title, self.analyzer.format_size(p.vss_used), self.analyzer.format_size(p.vss_max),
                        p.vss_copies, 'y' if p.vss_copies == 1 else 'ies')
                labels.append({'text': text, 'anchor': anchor, 'side': 'below' if kind == 'vss' else 'above',
                               'kind': kind, 'part': p, 'meter': kind == 'vss'})
        lanes = {'above': [], 'below': []}
        for lab in sorted(labels, key=lambda l: l['anchor']):
            w = fm.horizontalAdvance(lab['text']) + (12 if lab['kind'] else 0) + 6
            lab['w'] = max(w, 150) if lab.get('meter') else w
            if lab['w'] > x1 - x0:                         # a narrow window: shorten, never overflow
                icon = 12 if lab['kind'] else 0
                lab['w'] = x1 - x0
                lab['text'] = fm.elidedText(lab['text'], Qt.ElideRight, int(lab['w'] - icon - 6))
            x = max(x0, min(lab['anchor'] - lab['w'] / 2, x1 - lab['w']))
            rows = lanes[lab['side']]
            for i, row in enumerate(rows):
                if not row or x >= row[-1] + 10:
                    break
                shifted = row[-1] + 10
                if shifted + lab['w'] <= x1 and shifted - lab['anchor'] < 260:
                    x = shifted
                    break
            else:
                rows.append([])
                i = len(rows) - 1
            rows[i].append(x + lab['w'])
            lab['lane'], lab['x'] = i, x
        return labels, len(lanes['above']), len(lanes['below'])

    def _geometry(self):
        x0, x1 = self.PAD, self.width() - self.PAD
        labels, up, down = self._labels(x0, x1)
        below_h = sum(self.VSS_LANE_H if any(l.get('meter') and l['lane'] == i and l['side'] == 'below'
                                             for l in labels) else self.LANE_H for i in range(down))
        bar_top = self.PAD + up * self.LANE_H + (6 if up else 0)
        return x0, x1, labels, up, down, bar_top, below_h

    def resizeEvent(self, event):
        _, _, _, up, down, bar_top, below_h = self._geometry()
        h = bar_top + self.BAR_H + (8 if down else 0) + below_h + self.PAD
        if self.minimumHeight() != h:
            self.setMinimumHeight(h)
            self.setMaximumHeight(h)
        super().resizeEvent(event)

    # ---- drawing ---------------------------------------------------------------------
    def paintEvent(self, event):
        x0, x1, labels, up, down, bar_top, below_h = self._geometry()
        bar_bot = bar_top + self.BAR_H
        g = QPainter(self)
        g.setRenderHint(QPainter.Antialiasing)
        self._hits = []
        fm = QFontMetrics(self.font, self)
        g.fillRect(QRectF(x0, bar_top, x1 - x0, self.BAR_H), QColor('#0B1220'))
        for p, sx, sw in self._segments(x0, x1 - x0):
            bg, border, fg = self.color_fn(p)
            rect = QRectF(sx, bar_top, sw, self.BAR_H)
            g.setPen(QPen(QColor(border), 3 if sw > 10 else 1))
            g.setBrush(QColor(bg))
            g.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 4, 4)
            self._hits.append((rect, self._part_tip(p)))
            has_track = bool(p.extents)
            name, size = self._name(p), self.analyzer.format_size(p.total_size)
            fb = QFontMetrics(self.bold, self)
            g.setPen(QColor(fg))
            if has_track and fb.horizontalAdvance('%s  %s' % (name, size)) + 12 <= sw:
                g.setFont(self.bold)
                g.drawText(QRectF(sx, bar_top + 3, sw, self.BAR_H / 2 - 1), Qt.AlignCenter, '%s  %s' % (name, size))
            elif not has_track and max(fb.horizontalAdvance(name), fm.horizontalAdvance(size)) + 12 <= sw:
                g.setFont(self.bold)
                g.drawText(QRectF(sx, bar_top + 6, sw, self.BAR_H / 2 - 4), Qt.AlignHCenter | Qt.AlignBottom, name)
                g.setFont(self.font)
                g.drawText(QRectF(sx, bar_top + self.BAR_H / 2 + 1, sw, self.BAR_H / 2 - 6),
                           Qt.AlignHCenter | Qt.AlignTop, size)
            if has_track:
                g.fillRect(QRectF(sx + 4, bar_top + self.BAR_H / 2 + 1, sw - 8, self.BAR_H / 2 - 7),
                           QColor(11, 18, 32, 150))
            total = max(1, p.total_size)
            for kind, title, colour in LAYOUT_KINDS:
                c = QColor(colour)
                for k, off, ln in (p.extents or []):
                    if k != kind:
                        continue
                    mx = sx + off / total * sw
                    mw = max(self.MIN_MARK, ln / total * sw)
                    mr = QRectF(mx, bar_top + self.BAR_H / 2 + 1, mw, self.BAR_H / 2 - 7)
                    g.fillRect(mr, c)
                    self._hits.append((mr.adjusted(-2, 0, 2, 0), '%s\noffset %s, %s' % (
                        title, self.analyzer.format_size(off), self.analyzer.format_size(ln))))
            if p.layout_note and p.fstype and str(p.fstype).upper() == 'NTFS' and not p.extents:
                self._hits.append((rect, self._part_tip(p) + '\n' + p.layout_note))
            if self.selected is not None:
                if p is self.selected:
                    g.setPen(QPen(QColor('#F8FAFC'), 2.5))
                    g.setBrush(Qt.NoBrush)
                    g.drawRoundedRect(rect.adjusted(-1, -1, 1, 1), 5, 5)
                else:
                    g.fillRect(rect.adjusted(1, 1, -1, -1), QColor(11, 18, 32, 120))

        # labels, lanes and leaders
        lane_y = {'above': [], 'below': []}
        y = bar_top - 6
        for i in range(up):
            lane_y['above'].append(y - (i + 1) * self.LANE_H)
        y = bar_bot + 8
        for i in range(down):
            lane_y['below'].append(y)
            y += self.VSS_LANE_H if any(l.get('meter') and l['side'] == 'below' and l['lane'] == i
                                        for l in labels) else self.LANE_H
        for lab in labels:
            ly = lane_y[lab['side']][lab['lane']]
            colour = QColor(dict((k, c) for k, _t, c in LAYOUT_KINDS).get(lab['kind'], '#94A3B8'))
            box = QRectF(lab['x'], ly, lab['w'], self.LANE_H - 4)
            # leader: from the bar edge at the anchor to the nearest point of the label
            ax = lab['anchor']
            lx = min(max(ax, box.left() + 6), box.right() - 6)
            g.setPen(QPen(colour, 1))
            if lab['side'] == 'above':
                g.drawLine(QPointF(ax, bar_top), QPointF(ax, bar_top - 4))
                g.drawLine(QPointF(ax, bar_top - 4), QPointF(lx, box.bottom()))
            else:
                g.drawLine(QPointF(ax, bar_bot), QPointF(ax, bar_bot + 4))
                g.drawLine(QPointF(ax, bar_bot + 4), QPointF(lx, box.top()))
            tx = box.left()
            if lab['kind']:
                g.fillRect(QRectF(tx, box.top() + 4, 8, 8), colour)
                tx += 12
            g.setFont(self.font)
            g.setPen(QColor('#E2E8F0' if lab['kind'] else '#94A3B8'))
            g.drawText(QRectF(tx, box.top(), box.right() - tx + 40, self.LANE_H - 4),
                       Qt.AlignLeft | Qt.AlignVCenter, lab['text'])
            if lab.get('meter'):
                self._meter(g, lab['part'], QRectF(box.left() + 12, box.top() + self.LANE_H - 2, lab['w'] - 12, 7))
        g.end()

    def _meter(self, g, p, r):
        """Shadow storage: used (solid), allocated (outlined), against the maximum (the track)."""
        mx = max(p.vss_max, p.vss_allocated, p.vss_used, 1)
        g.setPen(QPen(QColor('#475569'), 1))
        g.setBrush(QColor('#0F172A'))
        g.drawRect(r)
        g.setPen(Qt.NoPen)
        g.setBrush(QColor(250, 204, 21, 70))
        g.drawRect(QRectF(r.left(), r.top(), r.width() * p.vss_allocated / mx, r.height()))
        g.setBrush(QColor('#FACC15'))
        g.drawRect(QRectF(r.left(), r.top(), r.width() * p.vss_used / mx, r.height()))

    def _part_tip(self, p):
        lines = ['%s  %s' % ((p.mountpoint or p.device or '').rstrip('\\'), p.partition_type),
                 '%s, %s' % (p.fstype, self.analyzer.format_size(p.total_size))]
        if p.mft_bytes:
            lines.append('$MFT %s' % self.analyzer.format_size(p.mft_bytes))
        if p.usn_bytes:
            lines.append('USN journal %s on disk' % self.analyzer.format_size(p.usn_bytes))
        if p.vss_max or p.vss_copies:
            lines.append('Shadow storage %s used, %s allocated, %s max; %d copies%s' % (
                self.analyzer.format_size(p.vss_used), self.analyzer.format_size(p.vss_allocated),
                self.analyzer.format_size(p.vss_max), p.vss_copies,
                (', %s to %s UTC' % (p.vss_oldest.replace('T', ' ').rstrip('Z'), p.vss_newest.replace('T', ' ').rstrip('Z'))
                 if p.vss_oldest else '')))
            if p.vss_diff_volume and p.vss_diff_volume + ':' != (p.mountpoint or '').rstrip('\\'):
                lines.append('Stored on %s:' % p.vss_diff_volume)
        return '\n'.join(lines)

    def select(self, partition):
        self.selected = partition
        self.update()

    def mouseMoveEvent(self, event):
        pos = event.pos()
        for rect, tip in reversed(self._hits):
            if rect.contains(QPointF(pos)):
                QToolTip.showText(event.globalPos(), tip, self)
                return
        QToolTip.hideText()


PARTITION_HELP = (
    "<b>One card per disk.</b> Each physical disk is one container: its model, size, partition style (GPT or "
    "MBR) and whether the machine boots from it. Inside, every partition is a tile of its own, in its order on "
    "the disk, with an icon and a colour for what it is for - EFI system, MSR, Windows, data, recovery, Linux, "
    "swap. Tiles keep a readable width however small the partition; hover one for its device, type GUID and "
    "offset, click it to find its row in the table.<br><br>"
    "<b>The disk bar.</b> Under the tiles, the same disk as one bar: every partition at a readable width, "
    "and inside each NTFS volume its $MFT, USN journal and shadow-copy storage at their real positions, "
    "labels outside the marks.<br><br>"
    "<b>Usage.</b> Windows reports how full a volume is only when it mounts it, so a partition with no drive "
    "letter shows none rather than a misleading 0%. Paging files (pagefile.sys, swapfile.sys, hiberfil.sys) "
    "are files on a volume, not a kind of partition.<br><br>"
    "<b>Shadow Copies...</b> opens every shadow copy of this machine's volumes: where each one's store sits, "
    "what made it, and what changed since.")


# What a partition is for, one colour and one icon each: the tiles, the to-scale bar and the
# legend all read from here, so a colour means the same role everywhere on the window.
ROLES = {
    "efi": ("EFI system", "#22D3EE", "part_efi",
            "Holds the boot loader the firmware starts (FAT32). No drive letter."),
    "msr": ("MSR", "#64748B", "part_msr",
            "Microsoft reserved partition: kept by Windows on GPT disks, holds no file system."),
    "windows": ("Windows", "#4ADE80", "part_windows", "The volume Windows runs from."),
    "data": ("Data", "#60A5FA", "part_data", "A data volume."),
    "recovery": ("Recovery", "#FB923C", "part_recovery",
                 "Windows Recovery Environment (WinRE): repair and reset tools. No drive letter."),
    "linux": ("Linux", "#2DD4BF", "part_linux", "A Linux file system; Windows cannot read it."),
    "swap": ("Swap", "#A78BFA", "part_swap", "A Linux swap partition."),
    "unknown": ("Unknown", "#94A3B8", "part_unknown", "A partition whose type was not recognised."),
}
TILE_BG, TILE_EDGE, MUTED, BODY, TEXT = "#111A2E", "#24314A", "#94A3B8", "#E2E8F0", "#F8FAFC"


def partition_role(p):
    t = str(p.partition_type or "").lower()
    if p.is_swap or "swap" in t:
        return "swap"
    if p.is_linux or "linux" in t:
        return "linux"
    if p.is_efi_system or "efi" in t or t == "system":
        return "efi"
    if "reserved" in t or "msr" in t:
        return "msr"
    if "recovery" in t:
        return "recovery"
    mount = p.mountpoint or ""
    if p.is_system or (mount and os.path.isdir(os.path.join(mount, "Windows", "System32"))):
        return "windows"
    if mount or "basic" in t or "data" in t or str(p.fstype or "").upper() in ("NTFS", "EXFAT", "FAT32", "REFS"):
        return "data"
    return "unknown"


def role_colours(p):
    """(fill, border, text) for the to-scale bar, from the partition's role."""
    colour = ROLES[partition_role(p)][1]
    return colour, colour, "#0B1220"


def paging_files(p):
    """The paging and hibernation files a mounted Windows volume holds (files, not partitions)."""
    mount = p.mountpoint or ""
    if not mount or getattr(p, "source", "Current System") not in ("Current System", "Live"):
        return []
    out = []
    for name in ("pagefile.sys", "swapfile.sys", "hiberfil.sys"):
        try:
            if os.path.exists(os.path.join(mount, name)):
                out.append(name)
        except OSError:
            pass
    return out


def usage_known(p):
    """Windows reports how full a volume is only when it has mounted it (a drive letter)."""
    return bool(p.mountpoint) and not p.is_linux and bool(p.total_size)


def _icon_pixmap(name, colour, px):
    from ui.artifact_icons import artifact_icon
    icon = artifact_icon(name, colour)
    return icon.pixmap(px, px) if icon is not None else None


def _font(px, bold=False, upper=False):
    try:
        from ui import app_theme
        return app_theme.font("ui", px, QFont.Bold if bold else QFont.Normal, upper=upper,
                              spacing=106 if upper else 100)
    except Exception:
        f = QFont("Segoe UI", max(7, px - 4))
        f.setBold(bold)
        return f


class PartitionTiles(QWidget):
    """One disk's partitions side by side in their on-disk order, each a tile of its own with its
    icon, name, size, file system and how full it is. Widths follow size, but no tile is narrower
    than MIN_W, so a 16 MB MSR is as readable as a 900 GB C:; the to-scale bar below shows the
    real proportions."""

    MIN_W = 168
    GAP = 10
    H = 84
    clicked = pyqtSignal(object)

    def __init__(self, disk, analyzer, parent=None):
        super().__init__(parent)
        self.disk = disk
        self.analyzer = analyzer
        self.parts = sorted(disk.partitions, key=lambda p: p.partition_index)
        self.selected = None
        self._rects = []
        self.setMouseTracking(True)
        self.setMinimumHeight(self.H)
        self.setMinimumWidth(len(self.parts) * (self.MIN_W + self.GAP))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.f_name, self.f_body, self.f_small = _font(16, True), _font(13), _font(12)
        self.f_role = _font(10, True, True)

    def sizeHint(self):
        from PyQt5.QtCore import QSize
        return QSize(len(self.parts) * (self.MIN_W + self.GAP), self.H)

    def _widths(self):
        n = len(self.parts)
        avail = self.width() - self.GAP * (n - 1)
        extra = max(0, avail - n * self.MIN_W)
        total = float(sum(max(p.total_size, 1) for p in self.parts)) or 1.0
        # 60% of the spare width follows size, 40% is shared equally, so on a wide window the small
        # partitions' tiles grow too and say all they hold, while the big one stays the biggest.
        return [self.MIN_W + extra * (0.6 * max(p.total_size, 1) / total + 0.4 / n) for p in self.parts]

    def paintEvent(self, _event):
        from PyQt5.QtGui import QPainterPath
        g = QPainter(self)
        g.setRenderHint(QPainter.Antialiasing)
        self._rects = []
        x = 0.0
        fmt = self.analyzer.format_size
        for p, w in zip(self.parts, self._widths()):
            role = partition_role(p)
            title, colour, icon, _desc = ROLES[role]
            r = QRectF(x + 0.5, 0.5, w - 1, self.H - 1)
            self._rects.append((r, p))
            path = QPainterPath()
            path.addRoundedRect(r, 10, 10)
            # Each type its own background, as the bar's segments are: the role's colour as a tint
            # over the card, a solid band along the top.
            tint = QColor(colour)
            tint.setAlpha(60)
            g.fillPath(path, QColor(TILE_BG))
            g.fillPath(path, tint)
            g.save()
            g.setClipPath(path)
            g.fillRect(QRectF(r.left(), r.top(), r.width(), 4), QColor(colour))
            g.restore()
            sel = self.selected is p
            if self.selected is not None and not sel:
                g.fillPath(path, QColor(11, 18, 32, 110))
            g.setPen(QPen(QColor(TEXT if sel else colour), 2.5 if sel else 1))
            g.setBrush(Qt.NoBrush)
            g.drawPath(path)
            pad = 12
            inner = r.adjusted(pad, 12, -pad, -10)
            pm = _icon_pixmap(icon, colour, 24 if role == "windows" else 22)
            if pm is not None:
                g.drawPixmap(int(inner.left()), int(inner.top()), pm)
            name = (p.mountpoint or "").rstrip("\\") or title
            size_text = fmt(p.total_size)
            fmn, fms = QFontMetrics(self.f_name), QFontMetrics(self.f_small)
            g.setFont(self.f_name)
            g.setPen(QColor(TEXT))
            room = int(inner.width() - 30)
            g.drawText(QRectF(inner.left() + 30, inner.top(), max(0, room), 22), Qt.AlignLeft | Qt.AlignVCenter,
                       fmn.elidedText(name, Qt.ElideRight, max(0, room)))
            fs = "no file system" if role == "msr" else (p.fstype or "no file system")
            sub = "%s  \u00b7  %s  \u00b7  %s" % (
                size_text, title if (p.mountpoint or "") else "partition %d" % p.partition_index, fs)
            if p.volume_label:
                sub += '  \u00b7  "%s"' % p.volume_label
            g.setFont(self.f_small)
            g.setPen(QColor(colour))
            g.drawText(QRectF(inner.left(), inner.top() + 26, inner.width(), 16), Qt.AlignLeft | Qt.AlignVCenter,
                       fms.elidedText(sub, Qt.ElideRight, int(inner.width())))
            bar = QRectF(inner.left(), inner.bottom() - 5, inner.width(), 5)
            if usage_known(p):
                frac = max(0.0, min(1.0, p.used_size / float(p.total_size)))
                label = "%s used  \u00b7  %.0f%%" % (fmt(p.used_size), 100 * frac)
                lw = fms.horizontalAdvance(label)
                track = QPainterPath()
                bar = QRectF(inner.left(), inner.bottom() - 9, max(10.0, inner.width() - lw - 10), 5)
                track.addRoundedRect(bar, 2.5, 2.5)
                g.fillPath(track, QColor("#0B1220"))
                fill = QPainterPath()
                fill.addRoundedRect(QRectF(bar.left(), bar.top(), max(5.0, bar.width() * frac), 5), 2.5, 2.5)
                # One meaning: amber is "nearly full", never red, which is for what is urgent.
                g.fillPath(fill, QColor("#F59E0B" if frac >= 0.9 else colour))
                g.setPen(QColor(BODY))
                g.drawText(QRectF(bar.right() + 8, inner.bottom() - 16, lw + 2, 16), Qt.AlignLeft | Qt.AlignVCenter,
                           label)
            else:
                g.setPen(QColor(MUTED))
                g.drawText(QRectF(inner.left(), inner.bottom() - 16, inner.width(), 16), Qt.AlignLeft | Qt.AlignVCenter,
                           fms.elidedText("No drive letter" if not p.is_linux else "Not readable by Windows",
                                          Qt.ElideRight, int(inner.width())))
            x += w + self.GAP
        g.end()

    def _tip(self, p):
        role = partition_role(p)
        title, _c, _i, desc = ROLES[role]
        lines = ["%s - %s" % ((p.mountpoint or "").rstrip("\\") or "Partition %d" % p.partition_index, title),
                 desc, "", "Device: %s" % p.device, "Type: %s" % p.partition_type,
                 "File system: %s" % (p.fstype or "-"), "Size: %s" % self.analyzer.format_size(p.total_size)]
        if usage_known(p):
            lines.append("Used: %s (%.1f%%)" % (self.analyzer.format_size(p.used_size), p.percent_used))
        if p.volume_label:
            lines.append("Label: %s" % p.volume_label)
        if p.partition_offset:
            lines.append("Starts at: %s (%d bytes)" % (self.analyzer.format_size(p.partition_offset), p.partition_offset))
        if p.partition_guid:
            lines.append("Partition type GUID: %s" % p.partition_guid)
        held = paging_files(p)
        if held:
            lines.append("Holds: %s" % ", ".join(held))
        lines.append("")
        lines.append("Click to find it in the table below.")
        return "\n".join(lines)

    def mouseMoveEvent(self, event):
        for r, p in self._rects:
            if r.contains(QPointF(event.pos())):
                self.setCursor(Qt.PointingHandCursor)
                QToolTip.showText(event.globalPos(), self._tip(p), self)
                return
        self.unsetCursor()
        QToolTip.hideText()

    def select(self, partition):
        self.selected = partition
        self.update()

    def mousePressEvent(self, event):
        for r, p in self._rects:
            if r.contains(QPointF(event.pos())):
                self.select(p)
                self.clicked.emit(p)
                return


class PartitionVisualizationWidget(QWidget):
    """One disk as one container: its header, its partitions as separate tiles, the disk drawn to
    scale with the volumes' own structures, and a legend of what the colours on it mean."""

    partition_clicked = pyqtSignal(object)

    def __init__(self, disk: DiskInfo, analyzer: PartitionAnalyzer, parent=None):
        super().__init__(parent)
        self.disk = disk
        self.analyzer = analyzer
        self.init_ui()

    def _get_partition_color(self, partition: PartitionInfo) -> tuple:
        return role_colours(partition)

    def select(self, partition):
        """Outline one partition in the tiles and on the bar (None: no outline)."""
        mine = partition if partition in self.disk.partitions else None
        self.tiles.select(mine)
        self.bar.select(mine)

    def _pill(self, text, tip=None):
        pill = QLabel(text)
        pill.setProperty("role", "readout")
        if tip:
            pill.setToolTip(tip)
        return pill

    def init_ui(self):
        from ui import app_theme
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = app_theme.set_card(app_theme.Card())
        outer.addWidget(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(10)
        icon = QLabel()
        pm = _icon_pixmap("part_data", "#A5B4FC", 30)
        if pm is not None:
            icon.setPixmap(pm)
        head.addWidget(icon)
        name = QLabel("Disk %d" % self.disk.disk_index)
        name.setFont(_font(20, True))
        name.setProperty("keepStyle", True)
        name.setStyleSheet("color: %s; background: transparent;" % TEXT)
        head.addWidget(name)
        model = QLabel(self.disk.model or "")
        model.setProperty("role", "muted")
        model.setFont(_font(14))
        head.addWidget(model)
        head.addSpacing(8)
        style = getattr(self.disk, "partition_style", "") or (
            self.disk.partitions[0].partition_style if self.disk.partitions else "")
        head.addWidget(self._pill(self.analyzer.format_size(self.disk.size), "The disk's whole size"))
        if style and style != "Unknown":
            head.addWidget(self._pill(style, "GPT: GUID partition table (UEFI); MBR: master boot record (BIOS)"))
        head.addWidget(self._pill("%d partition%s" % (len(self.disk.partitions),
                                                     "" if len(self.disk.partitions) == 1 else "s")))
        if self.disk.is_bootable:
            head.addWidget(self._pill("Boots this machine", "The disk the firmware starts Windows from"))
        if self.disk.is_usb:
            head.addWidget(self._pill("USB"))
        if self.disk.is_removable:
            head.addWidget(self._pill("Removable"))
        head.addStretch(1)
        source = getattr(self.disk, "source", "") or ""
        if source:
            src = QLabel(source)
            src.setProperty("role", "muted")
            head.addWidget(src)
        layout.addLayout(head)

        cap = QLabel("Partitions, in their order on the disk")
        cap.setProperty("role", "caption")
        layout.addWidget(cap)
        self.tiles = PartitionTiles(self.disk, self.analyzer)
        self.tiles.clicked.connect(self.partition_clicked.emit)
        self.tiles.clicked.connect(self.select)
        layout.addWidget(self.tiles)

        self.bar = PartitionBar(self.disk, self.analyzer, self._get_partition_color)
        layout.addWidget(self.bar)

        legend = QHBoxLayout()
        legend.setSpacing(16)
        present = []
        for p in sorted(self.disk.partitions, key=lambda q: q.partition_index):
            role = partition_role(p)
            if role not in present:
                present.append(role)
        entries = [(ROLES[r][0], ROLES[r][1], ROLES[r][2], ROLES[r][3]) for r in present]
        entries += [(title, colour, None, None) for _k, title, colour in LAYOUT_KINDS]
        for title, colour, icon_name, desc in entries:
            item = QHBoxLayout()
            item.setSpacing(6)
            sw = QLabel()
            if icon_name:
                pmx = _icon_pixmap(icon_name, colour, 16)
                if pmx is not None:
                    sw.setPixmap(pmx)
            else:
                sw.setFixedSize(11, 11)
                sw.setProperty("keepStyle", True)
                sw.setStyleSheet("background: %s; border-radius: 3px;" % colour)
            text = QLabel(title)
            text.setProperty("role", "muted")
            if desc:
                sw.setToolTip(desc)
                text.setToolTip(desc)
            item.addWidget(sw)
            item.addWidget(text)
            legend.addLayout(item)
        legend.addStretch(1)
        layout.addLayout(legend)


class PartitionWindow(QDialog):
    """
    Main window for displaying partition and volume analysis.
    Features a modern cyberpunk-themed UI with neon accents.
    """
    
    def __init__(self, db_paths=None, parent=None):
        """
        Initialize the PartitionWindow.
        
        Args:
            db_paths: List of tuples (source_name, db_path) or single db_path string for backward compatibility
            parent: Parent widget
        """
        super().__init__(parent)
        self.analyzer = PartitionAnalyzer()
        self.disks = []
        
        # Normalize db_paths to list of tuples
        if db_paths is None:
            self.db_paths = []
        elif isinstance(db_paths, str):
            # Backward compatibility: single path string
            self.db_paths = [('Current System', db_paths)]
        elif isinstance(db_paths, list):
            if len(db_paths) > 0 and isinstance(db_paths[0], tuple):
                self.db_paths = db_paths
            else:
                # Convert list of paths to list of tuples
                self.db_paths = [(f'Source {i+1}', path) for i, path in enumerate(db_paths)]
        else:
            self.db_paths = []
        
        self.init_ui()
        self.load_partition_data()

        # Roles for what the inline sheets said; Refresh is the main action
        from ui.app_theme import apply_theme, set_variant
        apply_theme(self)
        set_variant(self._refresh_btn, "primary")
        set_variant(self._close_btn, "ghost")
    
    def init_ui(self):
        """Initialize the user interface"""
        self.setWindowTitle("Partition & Volume Analysis - Crow Eye")
        # Maximizable like every other analysis window: the disks and the table want the room.
        self.setWindowFlags(self.windowFlags() | Qt.WindowMinMaxButtonsHint)
        self.setMinimumSize(1200, 800)
        # Owned windows get no taskbar button on Windows, whatever their title
        # says - so a minimized Crow-Eye window had nowhere to show its name.
        # See CrowEyeStyles.give_window_a_taskbar_button for the measurements.
        try:
            from styles import CrowEyeStyles as _CES
            _CES.give_window_a_taskbar_button(self)
        except Exception:
            pass
        
        # The site look, set before the widgets exist (ui/app_theme.py). The
        # partition map keeps its own colours: the colour is the partition type.
        from ui.app_theme import begin_theme
        begin_theme(self)
        
        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)
        
        # Header
        header = self.create_header()
        main_layout.addWidget(header)
        
        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setStyleSheet("QFrame { background-color: rgba(99, 102, 241, 0.45); border: none;"
                                " max-height: 1px; margin: 6px 0; }")
        separator.setProperty("keepStyle", True)
        main_layout.addWidget(separator)
        
        # Disk visualization area (scrollable)
        self.disk_viz_scroll = QScrollArea()
        self.disk_viz_scroll.setWidgetResizable(True)
        self.disk_viz_scroll.setStyleSheet("""
            QScrollArea {
                background-color: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background-color: #1E293B;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background-color: #475569;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #00FFFF;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: transparent;
            }
        """)
        
        self.disk_viz_container = QWidget()
        # Transparent: each disk is its own card on the window's well.
        self.disk_viz_container.setStyleSheet("background: transparent;")
        self.disk_viz_container.setProperty("keepStyle", True)
        self.disk_viz_layout = QVBoxLayout(self.disk_viz_container)
        self.disk_viz_layout.setSpacing(15)
        self.disk_viz_scroll.setWidget(self.disk_viz_container)
        
        # 3 : 2, because a disk now carries label lanes above and below its bar
        main_layout.addWidget(self.disk_viz_scroll, 5)
        
        # Partition details: a card of its own, like the disks above it.
        from ui import app_theme
        table_card, table_body, _th = app_theme.section_card(
            "Partition details", "Every partition with its identifiers. Select a row to find it on its disk above.")
        self.partition_table = self.create_partition_table()
        self.partition_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.partition_table.setSelectionMode(QTableWidget.SingleSelection)
        self.partition_table.itemSelectionChanged.connect(self._row_selected)
        self.partition_table.setMinimumHeight(200)
        self.partition_table.horizontalHeader().setStretchLastSection(True)
        self.partition_table.verticalHeader().setDefaultSectionSize(30)
        table_body.addWidget(self.partition_table, 1)
        main_layout.addWidget(table_card, 3)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        refresh_btn = QPushButton("Refresh Analysis")
        self._refresh_btn = refresh_btn
        refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #10B981;
                color: #FFFFFF;
                border: 3px solid #34D399;
                border-radius: 8px;
                padding: 10px 20px;
                font-weight: bold;
                font-size: 13px;
                font-family: 'Segoe UI', sans-serif;
                min-width: 120px;
            }
            QPushButton:hover {
                background-color: #34D399;
                border: 3px solid #6EE7B7;
            }
            QPushButton:pressed {
                background-color: #059669;
            }
        """)
        refresh_btn.clicked.connect(self.refresh_data)
        button_layout.addWidget(refresh_btn)

        # Every shadow copy of this machine's volumes: where each one's storage sits, its size
        # against the maximum, what triggered it, and what changed between the copies.
        shadow_btn = QPushButton("Shadow Copies...")
        shadow_btn.setStyleSheet(refresh_btn.styleSheet().replace("#10B981", "#334155").replace(
            "#34D399", "#64748B").replace("#6EE7B7", "#94A3B8").replace("#059669", "#1E293B"))
        shadow_btn.clicked.connect(self._open_shadow_copies)
        button_layout.addWidget(shadow_btn)
        if getattr(self, "help_btn", None) is not None:
            button_layout.addWidget(self.help_btn)

        button_layout.addStretch()
        
        close_btn = QPushButton("Close")
        self._close_btn = close_btn
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #3B82F6;
                color: #FFFFFF;
                border: 3px solid #60A5FA;
                border-radius: 8px;
                padding: 10px 30px;
                font-weight: bold;
                font-size: 13px;
                font-family: 'Segoe UI', sans-serif;
                min-width: 120px;
            }
            QPushButton:hover {
                background-color: #60A5FA;
                border: 3px solid #93C5FD;
            }
            QPushButton:pressed {
                background-color: #1E40AF;
            }
        """)
        close_btn.clicked.connect(self.close)
        button_layout.addWidget(close_btn)
        
        main_layout.addLayout(button_layout)
    
    def create_header(self):
        """Create the header section with title and description"""
        header_widget = QWidget()
        header_layout = QVBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(5)
        
        # Title
        title = QLabel("PARTITION & VOLUME ANALYSIS")
        title.setStyleSheet("""
            QLabel {
                color: #00FFFF;
                font-size: 28px;
                font-weight: bold;
                font-family: 'Segoe UI', sans-serif;
                padding: 5px 0;
            }
        """)
        header_layout.addWidget(title)
        
        # Subtitle with boot mode (will be updated after data loads)
        boot_mode_text = f"Boot Mode: {self.analyzer.boot_mode} | Comprehensive disk and partition information with BIOS/UEFI and MBR/GPT detection"
        self.subtitle = QLabel(boot_mode_text)
        self.subtitle.setStyleSheet("""
            QLabel {
                color: #94A3B8;
                font-size: 13px;
                font-family: 'Segoe UI', sans-serif;
                padding: 0 0 5px 0;
            }
        """)
        header_layout.addWidget(self.subtitle)
        try:
            from ui import app_theme
            # The button sits in the bottom row (init_ui), so the disk cards keep their height.
            self.help_btn, self.help_panel = app_theme.how_it_works(PARTITION_HELP)
            header_layout.addWidget(self.help_panel)
        except Exception:
            pass

        return header_widget
    
    def create_partition_table(self):
        """Create the partition details table with enhanced forensic columns"""
        table = QTableWidget()
        table.setColumnCount(19)
        table.setHorizontalHeaderLabels([
            "Disk", "Volume", "Device", "Mount Point", "File System",
            "Total Size", "Used", "% Used", "Partition Style", "Type",
            "Volume Serial", "GUID", "Flags", "Boot Mode", "Disk Sig",
            "$MFT", "USN Journal", "Shadow Storage (used / max, copies)", "Source"
        ])
        
        # Set table style
        table.setStyleSheet("""
            QTableWidget {
                background-color: #0B1220;
                alternate-background-color: #0F172A;
                color: #E2E8F0;
                gridline-color: #1E293B;
                border: 3px solid #334155;
                border-radius: 8px;
                font-family: 'Segoe UI', sans-serif;
                font-size: 12px;
                selection-background-color: #3B82F6;
                selection-color: #FFFFFF;
            }
            QTableWidget::item {
                padding: 10px;
                border-bottom: 1px solid #1E293B;
                background-color: transparent;
            }
            QTableWidget::item:selected {
                background-color: #2563EB;
                color: #FFFFFF;
            }
            QTableWidget::item:hover {
                background-color: #1E293B;
            }
            QHeaderView::section {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1E293B, stop:1 #0F172A);
                color: #38BDF8;
                padding: 12px;
                border: none;
                border-right: 1px solid #334155;
                border-bottom: 2px solid #38BDF8;
                font-weight: bold;
                font-size: 12px;
            }
            QHeaderView::section:hover {
                background-color: #334155;
                color: #00FFFF;
            }
            QTableCornerButton::section {
                background-color: #0B1220;
                border: none;
                border-right: 1px solid #334155;
                border-bottom: 2px solid #38BDF8;
            }
            QScrollBar:vertical {
                background-color: #0B1220;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background-color: #475569;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #00FFFF;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: transparent;
            }
            QScrollBar:horizontal {
                background-color: #0B1220;
                height: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:horizontal {
                background-color: #475569;
                border-radius: 6px;
                min-width: 20px;
            }
            QScrollBar::handle:horizontal:hover {
                background-color: #00FFFF;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
            }
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
                background: transparent;
            }
        """)
        
        # Configure table properties
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.setSortingEnabled(True)
        table.verticalHeader().setVisible(False)
        
        # Set column widths
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(True)
        
        return table
    
    def load_partition_data(self, force_refresh=False):
        """Load partition data in background thread"""
        # Show loading state
        self.partition_table.setRowCount(0)
        
        # Clear visualizations
        while self.disk_viz_layout.count():
            child = self.disk_viz_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
                
        # The loading screen: each status the worker sends is a step with its own time.
        from ui.loading_panel import LoadingPanel
        self.disk_viz_scroll.setMaximumHeight(16777215)
        self.disk_viz_scroll.setMinimumHeight(300)
        self.loading_label = LoadingPanel(
            "Reading this machine's disks",
            "Each disk and its partitions as Windows' Storage module lists them (the Microsoft reserved "
            "partition too), then each NTFS volume's $MFT, USN journal and shadow-copy storage.")
        self.disk_viz_layout.addWidget(self.loading_label)
        
        self.worker = PartitionLoadWorker(self.db_paths, force_refresh)
        self.worker.finished.connect(self.on_data_loaded)
        self.worker.error.connect(self.on_load_error)
        self.worker.status.connect(self.on_status_update)
        self.worker.start()
        
    def on_status_update(self, message):
        """Update loading status message"""
        panel = getattr(self, 'loading_label', None)
        if panel is not None:
            if message == "Analysis complete":
                panel.finish()
            else:
                panel.start(message)
        
    def _open_shadow_copies(self):
        """The Shadow Copies window for this machine, in the case the Partition window reads."""
        from ui.shadow_copies_dialog import ShadowCopiesDialog
        case_root = None
        for _name, path in (self.db_paths or []):
            if path:
                parent = os.path.dirname(os.path.dirname(path))
                if os.path.isdir(os.path.join(parent, "Target_Artifacts")):
                    case_root = parent
                    break
        self._shadow_dialog = ShadowCopiesDialog(case_root, self)
        self._shadow_dialog.show()

    def refresh_data(self):
        """Refresh the partition data (force fresh analysis)"""
        self.load_partition_data(force_refresh=True)
    
    def on_data_loaded(self, disks):
        """Handle loaded partition data"""
        self.populate_disk_visualizations(disks)
        self.populate_partition_table(disks)
        
        # Update subtitle with source information
        sources = set(getattr(d, 'source', 'Unknown') for d in disks)
        source_text = ", ".join(sorted(sources)) if sources else "N/A"
        
        # Try to get boot mode from the first disk if available
        boot_mode = getattr(disks[0], 'boot_mode', 'Unknown') if disks else "Unknown"
        
        boot_mode_text = f"Boot Mode: {boot_mode} | Sources: {source_text} | {len(disks)} disk(s), {sum(len(d.partitions) for d in disks)} partition(s)"
        self.subtitle.setText(boot_mode_text)

    def on_load_error(self, error_msg):
        """Handle data loading error"""
        # Clear loading label safely before showing error
        if hasattr(self, 'loading_label') and self.loading_label:
            self.loading_label.deleteLater()
            self.loading_label = None

        from correlation_engine.gui.crow_eye_icons import apply_status_to_label
        error_label = QLabel()
        apply_status_to_label(error_label, "ERROR", f"Error loading partition data: {error_msg}")
        error_label.setStyleSheet("""
            QLabel {
                color: #EF4444;
                font-size: 14px;
                font-weight: bold;
                padding: 20px;
                background-color: rgba(239, 68, 68, 0.1);
                border: 3px solid #EF4444;
                border-radius: 8px;
            }
        """)
        self.disk_viz_layout.addWidget(error_label)

    def populate_disk_visualizations(self, disks):
        """Populate the disk visualization area"""
        # Clear existing widgets, but keep the loading_label if it exists
        for i in reversed(range(self.disk_viz_layout.count())):
            widget = self.disk_viz_layout.itemAt(i).widget()
            if widget and widget != self.loading_label:
                widget.deleteLater()

        # Safely remove the loading label now that we're about to populate
        if hasattr(self, 'loading_label') and self.loading_label:
            self.loading_label.deleteLater()
            self.loading_label = None

        # Add visualization for each disk
        if not disks:
            no_disks_label = QLabel("No disks found or loaded.")
            no_disks_label.setAlignment(Qt.AlignCenter)
            no_disks_label.setStyleSheet("color: #94A3B8; font-size: 16px; padding: 20px;")
            self.disk_viz_layout.addWidget(no_disks_label)
        else:
            # Sort disks by disk_index to ensure Disk 0 appears first
            sorted_disks = sorted(disks, key=lambda d: d.disk_index)
            self._viz_widgets = []
            for disk in sorted_disks:
                viz_widget = PartitionVisualizationWidget(disk, self.analyzer)
                viz_widget.partition_clicked.connect(self._select_partition_row)
                self.disk_viz_layout.addWidget(viz_widget)
                self._viz_widgets.append(viz_widget)
        
        # Add stretch at the end
        self.disk_viz_layout.addStretch()
        # As tall as the disks need, once the bars have laid themselves out (a bar sets its height
        # from its label lanes when it learns its width), so no empty band sits above the table.
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(120, self._fit_disk_area)

    def _fit_disk_area(self):
        widgets = getattr(self, "_viz_widgets", None) or []
        if not widgets:
            return
        lay = self.disk_viz_layout
        m = lay.contentsMargins()
        need = sum(w.sizeHint().height() for w in widgets) + lay.spacing() * max(0, len(widgets) - 1) \
            + m.top() + m.bottom() + 4
        # Up to roughly two disks on screen; more scroll.
        self.disk_viz_scroll.setMinimumHeight(min(need, 640))
        self.disk_viz_scroll.setMaximumHeight(need)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if getattr(self, "_viz_widgets", None):
            from PyQt5.QtCore import QTimer
            QTimer.singleShot(60, self._fit_disk_area)

    def _row_selected(self):
        """A table row selected: its partition outlined in its disk's tiles and bar."""
        rows = self.partition_table.selectionModel().selectedRows() if self.partition_table.selectionModel() else []
        device = self.partition_table.item(rows[0].row(), 2).text() if rows and \
            self.partition_table.item(rows[0].row(), 2) else None
        for viz in getattr(self, "_viz_widgets", []):
            match = next((p for p in viz.disk.partitions if device and p.device == device), None)
            viz.select(match)
            if match is not None:
                self.disk_viz_scroll.ensureWidgetVisible(viz.tiles)

    def _select_partition_row(self, partition):
        """A tile clicked: its row in the details table, selected and scrolled to."""
        for row in range(self.partition_table.rowCount()):
            item = self.partition_table.item(row, 2)
            if item is not None and item.text() == partition.device:
                self.partition_table.selectRow(row)
                self.partition_table.scrollToItem(item)
                return

    def populate_partition_table(self, disks):
        """Populate the partition details table"""
        # Off while filling: with sorting on, a refresh re-sorted after every
        # setItem and moved rows under the cells still being written.
        self.partition_table.setSortingEnabled(False)
        self.partition_table.setRowCount(0)
        
        # Sort disks and partitions for consistent display
        sorted_disks = sorted(disks, key=lambda d: d.disk_index)

        for disk in sorted_disks:
            sorted_partitions = sorted(disk.partitions, key=lambda p: p.partition_index)
            for partition in sorted_partitions:
                row = self.partition_table.rowCount()
                self.partition_table.insertRow(row)
                
                # Disk number (NEW - Column 0)
                disk_item = QTableWidgetItem(f"Disk {disk.disk_index}")
                disk_item.setForeground(QColor("#00FFFF"))  # Cyan for disk number
                self.partition_table.setItem(row, 0, disk_item)
                
                # Volume label
                self.partition_table.setItem(row, 1, QTableWidgetItem(partition.volume_label or "-"))
                
                # Device
                self.partition_table.setItem(row, 2, QTableWidgetItem(partition.device))
                
                # Mount point
                self.partition_table.setItem(row, 3, QTableWidgetItem(partition.mountpoint or "-"))
                
                # File system
                fs_item = QTableWidgetItem(partition.fstype)
                if partition_role(partition) == "msr":
                    # An MSR is never formatted; what Windows names there is not its file system.
                    fs_item = QTableWidgetItem("-")
                    fs_item.setToolTip("A Microsoft reserved partition holds no file system")
                if partition.is_linux:
                    fs_item.setForeground(QColor("#10B981"))  # Green for Linux FS
                self.partition_table.setItem(row, 4, fs_item)
                
                # Total size
                self.partition_table.setItem(row, 5, QTableWidgetItem(
                    self.analyzer.format_size(partition.total_size)))
                
                # Used. Windows reports how full a volume is only when it has mounted it: a
                # Linux file system or a partition with no drive letter would read 0, which
                # says "empty" - a claim nobody measured.
                if not usage_known(partition):
                    why = ("Windows cannot read a Linux file system's usage" if partition.is_linux
                           else "No drive letter: Windows reports no usage for it")
                    used_item = QTableWidgetItem("-")
                    used_item.setToolTip(why)
                    self.partition_table.setItem(row, 6, used_item)
                    percent_item = QTableWidgetItem("-")
                    percent_item.setToolTip(why)
                    self.partition_table.setItem(row, 7, percent_item)
                else:
                    self.partition_table.setItem(row, 6, QTableWidgetItem(
                        self.analyzer.format_size(partition.used_size)))

                    # % Used (with color coding)
                    percent_item = QTableWidgetItem(f"{partition.percent_used:.1f}%")
                    if partition.percent_used > 90:
                        percent_item.setForeground(QColor("#F59E0B"))  # Amber: nearly full (red is urgent only)
                    elif partition.percent_used > 75:
                        percent_item.setForeground(QColor("#FBBF24"))
                    else:
                        percent_item.setForeground(QColor("#10B981"))  # Green
                    self.partition_table.setItem(row, 7, percent_item)
                
                # Partition Style (MBR/GPT)
                style_item = QTableWidgetItem(partition.partition_style)
                if partition.partition_style == "GPT":
                    style_item.setForeground(QColor("#00FFFF"))  # Cyan for GPT
                elif partition.partition_style == "MBR":
                    style_item.setForeground(QColor("#F59E0B"))  # Orange for MBR
                self.partition_table.setItem(row, 8, style_item)
                
                # Type, and what the partition is for
                role_title = ROLES[partition_role(partition)][0]
                type_item = QTableWidgetItem("%s  (%s)" % (role_title, partition.partition_type)
                                             if role_title.lower() not in str(partition.partition_type).lower()
                                             else partition.partition_type)
                type_item.setForeground(QColor(ROLES[partition_role(partition)][1]))
                held = paging_files(partition)
                if held:
                    type_item.setToolTip("Holds " + ", ".join(held))
                self.partition_table.setItem(row, 9, type_item)
                
                # Volume Serial
                self.partition_table.setItem(row, 10, QTableWidgetItem(partition.volume_serial or "-"))
                
                # Partition GUID
                guid_text = partition.partition_guid[:36] if partition.partition_guid else "-"
                self.partition_table.setItem(row, 11, QTableWidgetItem(guid_text))
                
                # Flags
                flags = []
                if partition.is_boot:
                    flags.append("BOOT")
                if partition.is_system:
                    flags.append("SYSTEM")
                if partition.is_swap:
                    flags.append("SWAP")
                if partition.is_linux:
                    flags.append("LINUX")
                if partition.is_efi_system:
                    flags.append("EFI")
                if partition.is_active:
                    flags.append("ACTIVE")
                if partition.is_hidden:
                    flags.append("HIDDEN")
                
                flags_item = QTableWidgetItem(", ".join(flags) if flags else "-")
                if partition.is_boot or partition.is_efi_system:
                    flags_item.setForeground(QColor("#00FFFF"))  # Cyan for boot/EFI
                elif partition.is_system:
                    flags_item.setForeground(QColor("#3B82F6"))  # Blue for system
                elif partition.is_hidden:
                    flags_item.setForeground(QColor("#94A3B8"))  # Hidden is normal for EFI/MSR/recovery
                self.partition_table.setItem(row, 12, flags_item)
                
                # Boot Mode (from disk)
                boot_mode = disk.boot_mode if hasattr(disk, 'boot_mode') else "Unknown"
                boot_item = QTableWidgetItem(boot_mode)
                if boot_mode == "UEFI":
                    boot_item.setForeground(QColor("#00FFFF"))  # Cyan for UEFI
                elif boot_mode == "BIOS":
                    boot_item.setForeground(QColor("#F59E0B"))  # Orange for BIOS
                self.partition_table.setItem(row, 13, boot_item)
                
                # Disk Signature
                disk_sig = partition.disk_signature if partition.disk_signature else "-"
                self.partition_table.setItem(row, 14, QTableWidgetItem(disk_sig))
                
                # The volume's own structures (volume_layout.py)
                fmt = self.analyzer.format_size
                self.partition_table.setItem(row, 15, QTableWidgetItem(
                    fmt(partition.mft_bytes) if partition.mft_bytes else "-"))
                self.partition_table.setItem(row, 16, QTableWidgetItem(
                    fmt(partition.usn_bytes) if partition.usn_bytes else "-"))
                if partition.vss_max or partition.vss_copies:
                    vss_text = "%s / %s, %d" % (fmt(partition.vss_used), fmt(partition.vss_max), partition.vss_copies)
                else:
                    vss_text = "-"
                vss_item = QTableWidgetItem(vss_text)
                if partition.layout_note:
                    vss_item.setToolTip(partition.layout_note)
                self.partition_table.setItem(row, 17, vss_item)

                # Source (last column)
                source = getattr(partition, 'source', getattr(disk, 'source', 'Unknown'))
                source_item = QTableWidgetItem(source)
                # Color code by source type
                if 'Live' in source or 'Current' in source:
                    source_item.setForeground(QColor("#10B981"))  # Green for live
                elif 'Offline' in source or 'JSON' in source:
                    source_item.setForeground(QColor("#F59E0B"))  # Orange for offline
                else:
                    source_item.setForeground(QColor("#94A3B8"))  # Gray for current/unknown
                self.partition_table.setItem(row, 18, source_item)
        
        # Resize columns to content
        self.partition_table.resizeColumnsToContents()
        self.partition_table.setSortingEnabled(True)


def main():
    """Test function to display the partition window"""
    from PyQt5.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    window = PartitionWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
