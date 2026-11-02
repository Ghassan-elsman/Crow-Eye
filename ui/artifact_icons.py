"""The forensic-artifact icons, shared with Crow-Eye Sentinel.

The line drawings are Sentinel's artifact family icons (sentinel console/demo/
icons.jsx, FAMILY_PATHS): a 24-unit grid, a 1.8 stroke with round caps and joins,
no fill, so the desktop and the console show an artifact the same way. Offline
Importer, Forensics Images and Crow-Claw Collector have no family of their own
there; they take the console's Folder, Layers and Register drawings.

Each icon is drawn from its SVG at every size Qt asks for, so it stays sharp,
and in one colour chosen for the button it sits on. Arc flags are written out
("a4 4 0 0 0 5.7 0", not "a4 4 0 005.7 0"): Qt's SVG reader misreads the
packed form browsers accept, and the drawing comes out as a stray line.
"""
from PyQt5 import QtCore, QtGui

_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
        'fill="none" stroke="{c}" stroke-width="1.8" stroke-linecap="round" '
        'stroke-linejoin="round">{body}</svg>')

DRAWINGS = {
    "registry": '<rect x="4" y="4" width="7" height="7" rx="1"/><rect x="13" y="4" width="7" height="7" rx="1"/>'
                '<rect x="4" y="13" width="7" height="7" rx="1"/><rect x="13" y="13" width="7" height="7" rx="1"/>',
    "prefetch": '<path d="M13 3L6 13h5l-1 8 7-10h-5z"/>',
    "amcache": '<ellipse cx="12" cy="6" rx="7" ry="2.6"/><path d="M5 6v12c0 1.4 3.1 2.6 7 2.6s7-1.2 7-2.6V6"/>'
               '<path d="M5 12c0 1.4 3.1 2.6 7 2.6s7-1.2 7-2.6"/>',
    "shimcache": '<path d="M4 7h16M4 12h16M4 17h10"/>',
    "lnk_jumplists": '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/>'
                     '<path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
    "event_logs": '<rect x="5" y="3.5" width="14" height="17" rx="2"/><path d="M8.5 8h7M8.5 12h7M8.5 16h4"/>',
    "mftusn": '<rect x="3.5" y="5" width="7" height="14" rx="1.5"/><rect x="13.5" y="5" width="7" height="14" rx="1.5"/>'
              '<path d="M10.5 12h3"/>',
    "srum": '<path d="M4 19V11M9 19V6M14 19v-9M19 19V4"/>',
    "recycle_bin": '<path d="M5 7h14M10 7V4.5h4V7M7 7l1 13h8l1-13"/>',
    "disks": '<rect x="3.5" y="7" width="17" height="10" rx="2"/><circle cx="16.5" cy="12" r="1.2" fill="{c}"/>'
             '<path d="M6.5 12h5"/>',
    "browser": '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.6 2.6 2.6 14.4 0 17M12 3.5c-2.6 2.6-2.6 14.4 0 17"/>',
    "accounts": '<circle cx="9" cy="8.5" r="3"/><path d="M3.5 19c0-3 2.5-5 5.5-5s5.5 2 5.5 5"/>'
                '<circle cx="16.5" cy="9.5" r="2.4"/><path d="M15 14.2c3 .2 5.5 1.9 5.5 4.8"/>',
    "folder": '<path d="M3.5 7.5a2 2 0 0 1 2-2h4l2 2h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/>',
    "layers": '<path d="M12 4l8.5 4.5L12 13 3.5 8.5z"/><path d="M3.5 12.5L12 17l8.5-4.5"/><path d="M3.5 16.5L12 21l8.5-4.5"/>',
    "register": '<rect x="4" y="5" width="16" height="11" rx="2" stroke-dasharray="3 2.4"/><path d="M12 8v5M9.5 10.5h5M9 20h6"/>',
    # App Acquisition (desktop only): a program window, taken down into the case.
    "app_acquisition": '<rect x="4.5" y="3.5" width="15" height="9.5" rx="1.8"/><path d="M4.5 6.8h15"/>'
                       '<path d="M12 9.5v9M8.8 15.4l3.2 3.2 3.2-3.2"/><path d="M5 20.5h14"/>',
    # File Browser (desktop only): a folder tree - a root, two branches, a leaf.
    "file_browser": '<rect x="3.5" y="3.5" width="7" height="5" rx="1.2"/><path d="M7 8.5v9.5h4.5M7 13h4.5"/>'
                    '<rect x="11.5" y="10.5" width="9" height="5" rx="1.2"/><rect x="11.5" y="16.5" width="9" height="4" rx="1.2"/>',
    # Partitions by what they are for (the Partition window's tiles and legend).
    "part_efi": '<rect x="5" y="5" width="14" height="14" rx="2.5"/><path d="M12 8.3v3.6"/>'
                '<path d="M9.3 10.1a3.9 3.9 0 1 0 5.4 0"/>',
    "part_msr": '<rect x="5.5" y="10.5" width="13" height="9.5" rx="2"/><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5"/>',
    # The Windows logo, its four panes filled so the volume Windows runs from reads at a glance.
    "part_windows": '<path d="M3.2 5.7l7.6-1.1v7.3H3.2z" fill="{c}" stroke="none"/>'
                    '<path d="M12.4 4.3l8.4-1.2v8.8h-8.4z" fill="{c}" stroke="none"/>'
                    '<path d="M3.2 13.4h7.6v7.3l-7.6-1.1z" fill="{c}" stroke="none"/>'
                    '<path d="M12.4 13.4h8.4v8.8l-8.4-1.2z" fill="{c}" stroke="none"/>',
    "part_data": '<rect x="3.5" y="7" width="17" height="10" rx="2"/><circle cx="16.5" cy="12" r="1.2" fill="{c}"/>'
                 '<path d="M6.5 12h5"/>',
    "part_recovery": '<path d="M4.6 12a7.4 7.4 0 1 0 2.2-5.3"/><path d="M4.5 3.8v4.3h4.3"/>',
    "part_linux": '<rect x="3.5" y="5" width="17" height="14" rx="2"/><path d="M7 9.5l3 2.5-3 2.5M12.5 15h4.5"/>',
    "part_swap": '<path d="M5 8.5h13l-3.5-3.5"/><path d="M19 15.5H6l3.5 3.5"/>',
    "part_unknown": '<circle cx="12" cy="12" r="8.5"/><path d="M9.6 9.7a2.5 2.5 0 1 1 3.5 2.3c-0.6 0.3 -1 0.8 -1 1.5v0.5"/>'
                    '<circle cx="12" cy="16.9" r="0.7" fill="{c}"/>',
    # Parse Offline Artifacts (desktop only): a collected file, run through the parsers.
    "parse_offline": '<path d="M6 3.5h8l4 4v13H6z"/><path d="M14 3.5v4h4"/><path d="M10 11l5 3-5 3z"/>',
    # Shadow Copies (desktop only): an earlier copy behind the volume, and a clock for when.
    "shadow_copies": '<rect x="7.5" y="3.5" width="13" height="10" rx="1.8" stroke-dasharray="2.6 2.2"/>'
                     '<rect x="3.5" y="8.5" width="13" height="12" rx="1.8"/>'
                     '<circle cx="10" cy="14.5" r="3.4"/><path d="M10 12.8v1.9l1.3.9"/>',
    # Parse all Artifacts (desktop only): the machine's artifacts as stacked layers,
    # read through a lens.
    "parse_all": '<path d="M10.5 3.5l7 3.7-7 3.7-7-3.7z"/><path d="M3.5 11l7 3.7 2.6-1.4"/>'
                 '<path d="M3.5 14.8l7 3.7 1-.5"/><circle cx="17.2" cy="16.4" r="3.4"/>'
                 '<path d="M19.7 18.9l2 2"/>',
    # Run Correlation (desktop only): three findings joined into one picture.
    "correlate": '<circle cx="5.5" cy="7" r="2.4"/><circle cx="18.5" cy="7" r="2.4"/>'
                 '<circle cx="12" cy="18.5" r="2.4"/><path d="M7.9 7h8.2M6.7 9.1l4.1 7.3M17.3 9.1l-4.1 7.3"/>',
}

# The two main actions' animation frames, phase 0..1: a scan line sweeping down the
# layers (Parse all), the nodes lighting in turn along their links (Run Correlation).
_CORRELATE_NODES = ((5.5, 7.0), (18.5, 7.0), (12.0, 18.5))
_CORRELATE_LINKS = ("M7.9 7h8.2", "M17.3 9.1l-4.1 7.3", "M10.8 16.4l-4.1-7.3")


def _parse_all_frame(phase):
    y = 3.0 + 16.0 * phase
    fade = min(1.0, phase / 0.15, (1.0 - phase) / 0.15)
    return (DRAWINGS["parse_all"]
            + '<path d="M2.5 %.2fh12.5" stroke-width="1.3" stroke-opacity="%.2f"/>' % (y, max(0.0, fade)))


def _correlate_frame(phase):
    k = int(phase * 3) % 3
    x, y = _CORRELATE_NODES[k]
    return (DRAWINGS["correlate"]
            + '<circle cx="%.1f" cy="%.1f" r="2.4" fill="{c}"/>' % (x, y)
            + '<path d="%s" stroke-width="2.8"/>' % _CORRELATE_LINKS[k])


ANIMATED = {"parse_all": _parse_all_frame, "correlate": _correlate_frame}


def animation_frames(name, color, count=24, sizes=(20, 22, 24, 32, 44, 48)):
    """``count`` QIcons of an ANIMATED drawing, phase 0..1, rendered once and
    cached: a tick of the animation only swaps a ready icon."""
    make = ANIMATED.get(name)
    if make is None:
        return []
    key = ("frames", name, color, count)
    if key not in _cache:
        frames = []
        for i in range(count):
            body = make(i / float(count)).replace("{c}", color)
            frames.append(_render(_SVG.format(c=color, body=body), sizes))
        _cache[key] = frames
    return _cache[key]

# Light on the blue parser buttons (#2563EB -> #1E40AF): the same near-white as the
# button text, tinted towards the blue so it sits in the button rather than on it.
ON_BLUE = "#EAF1FF"

# main window attribute -> drawing
MAIN_BUTTONS = {
    "registrybutton": "registry",
    "lnkbutton": "lnk_jumplists",
    "Prefetchbutton": "prefetch",
    "ShimCacheButton": "shimcache",
    "AmcacheButton": "amcache",
    "MFT_USN_CorrelateButton": "mftusn",
    "logbutton": "event_logs",
    "RecycleBinButton": "recycle_bin",
    "SRUMButton": "srum",
    "BrowserButton": "browser",
    "PartitionButton": "disks",
    "CrowClawButton": "register",
    "AppAcquisitionButton": "app_acquisition",
    "LiveAppAcquisitionButton": "app_acquisition",
    "FileBrowserButton": "file_browser",
    "LiveFileBrowserButton": "file_browser",
    "OfflineImporterButton": "folder",
    "ImageParsingButton": "layers",
    "ParseOfflineArtifactsButton": "parse_offline",
    "ShadowCopiesButton": "shadow_copies",
}

# The main window's artifact tabs (attribute -> drawing): the same drawings as the
# buttons, in a light slate that reads on the dark tab strip, selected or not.
ON_DARK = "#CBD5E1"
MAIN_TABS = {
    "Registry_Tab": "registry",
    "filesActivity_tab": "folder",
    "Prefetch_tab": "prefetch",
    "LNK_JL_Tab": "lnk_jumplists",
    "Logs_tab": "event_logs",
    "ShimCache_main_tab": "shimcache",
    "Amcache_main_tab": "amcache",
    "MFT_USN_main_tab": "mftusn",
    "RecycleBin_main_tab": "recycle_bin",
    "SRUM_main_tab": "srum",
    "Browser_main_tab": "browser",
}

_cache = {}


def artifact_icon(name, color=ON_BLUE):
    """A QIcon of one drawing in one colour, rendered at 16-64 px so every size
    Qt asks for is drawn, not scaled. None for an unknown name."""
    body = DRAWINGS.get(name)
    if body is None:
        return None
    key = (name, color)
    if key not in _cache:
        _cache[key] = _render(_SVG.format(c=color, body=body.replace("{c}", color)))
    return _cache[key]


def tinted_svg_icon(path, color, ink="white"):
    """A one-colour SVG file (drawn in `ink`) as a QIcon in `color`, so one
    drawing serves a white-on-red button and a dark sidebar alike. None when the
    file cannot be read."""
    key = (path, color)
    if key not in _cache:
        try:
            with open(path, encoding="utf-8") as f:
                svg = f.read()
        except OSError:
            return None
        _cache[key] = _render(svg.replace(f'"{ink}"', f'"{color}"'))
    return _cache[key]


def _render(svg, sizes=(16, 18, 20, 24, 32, 48, 64)):
    from PyQt5.QtSvg import QSvgRenderer
    renderer = QSvgRenderer(QtCore.QByteArray(svg.encode("utf-8")))
    icon = QtGui.QIcon()
    for px in sizes:
        image = QtGui.QImage(px, px, QtGui.QImage.Format_ARGB32_Premultiplied)
        image.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(image)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        renderer.render(painter)
        painter.end()
        icon.addPixmap(QtGui.QPixmap.fromImage(image))
    return icon


def apply_main_button_icons(ui, size=16):
    """Put the artifact icons on the main window's parser buttons and on its
    artifact tabs."""
    for attr, name in MAIN_BUTTONS.items():
        button = getattr(ui, attr, None)
        icon = artifact_icon(name) if button is not None else None
        if icon is not None:
            button.setIcon(icon)
            button.setIconSize(QtCore.QSize(size, size))
    tabs = getattr(ui, "main_tab", None)
    if tabs is not None:
        tabs.setIconSize(QtCore.QSize(size, size))
        for attr, name in MAIN_TABS.items():
            page = getattr(ui, attr, None)
            index = tabs.indexOf(page) if page is not None else -1
            icon = artifact_icon(name, ON_DARK)
            if index >= 0 and icon is not None:
                tabs.setTabIcon(index, icon)
