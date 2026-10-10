"""IDE-style colouring for Crow-Eye's logs - one highlighter, used everywhere.

Settings -> Logs, the full-log viewer, the parse dialog's lower pane and the
chain-of-custody raw JSON all show the same kinds of line:

    2026-10-08 09:13:46,252 [ERROR] Artifacts_Collectors.run.prefetch: Failed ...
    09:13:46.252  WARN   [PREF]  1 file skipped ...
    "source_sha256": "9f2c...",

``LogHighlighter`` colours them block by block (QSyntaxHighlighter only ever
sees one line, so it stays cheap on a 256 KB tail). The palette is the one
place colours live; ``level_of(line)`` is shared with the level filters.
"""
import re

from PyQt5 import QtGui

# --- palette (dark background #0B1226 / rgba(0,10,20)) ---------------------------
PALETTE = {
    "time": "#64748B",       # timestamps
    "error": "#F87171",      # ERROR / CRITICAL / FAIL / Traceback
    "warning": "#FBBF24",    # WARNING / WARN
    "info": "#38BDF8",       # INFO
    "debug": "#64748B",      # DEBUG
    "ok": "#4ADE80",         # OK / Completed / success
    "logger": "#C084FC",     # logger name
    "tag": "#2DD4BF",        # [Tag]
    "path": "#93C5FD",       # Windows paths, URLs
    "number": "#FDBA74",     # numbers, sizes, durations
    "string": "#86EFAC",     # quoted strings
    "hash": "#A78BFA",       # SHA-256, GUIDs
    "key": "#7DD3FC",        # JSON keys
    "text": "#E2E8F0",       # default foreground
}

LEVELS = ("ERROR", "WARNING", "INFO", "DEBUG")

_TS = re.compile(r"^\s*(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?|\d{2}:\d{2}:\d{2}(?:[.,]\d{1,3})?)")
_LEVEL = re.compile(r"\[(ERROR|CRITICAL|FATAL|FAIL|FAILED|WARNING|WARN|INFO|DEBUG|OK|SUCCESS|"
                    r"Completed|Error|Warning|Cancelled)\]|(?<![\w\[])(ERROR|CRITICAL|WARNING|WARN|"
                    r"INFO|DEBUG|OK|FAIL)(?=\s{2})")
_LOGGER = re.compile(r"\]\s+([A-Za-z_][\w.]*):\s")
_TAG = re.compile(r"\[[A-Za-z][\w &./-]{0,40}\]")
_PATH = re.compile(r"(?:[A-Za-z]:[\\/][^\s\"'|,;)]*|\\\\[^\s\"'|,;)]+|https?://[^\s\"'|,;)]+)")
_NUMBER = re.compile(r"(?<![\w.#-])-?\d[\d,]*(?:\.\d+)?(?:\s?(?:ms|s|KB|MB|GB|B|%|rows?|records?))?(?![\w.])")
_STRING = re.compile(r"\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\\n]|\\.)*'")
_HASH = re.compile(r"\b[0-9a-fA-F]{32,64}\b|\{?[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                   r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\}?")
_JSON_KEY = re.compile(r"^\s*(\"[^\"]+\")\s*:")
_TRACEBACK = re.compile(r"^(Traceback \(most recent call last\):|\s+File \".*\", line \d+|\w*Error: .*)$")

_LEVEL_KIND = {
    "ERROR": "error", "CRITICAL": "error", "FATAL": "error", "FAIL": "error", "FAILED": "error",
    "Error": "error", "WARNING": "warning", "WARN": "warning", "Warning": "warning",
    "INFO": "info", "DEBUG": "debug", "OK": "ok", "SUCCESS": "ok", "Completed": "ok",
    "Cancelled": "warning",
}


def level_of(line):
    """'ERROR' / 'WARNING' / 'INFO' / 'DEBUG' / '' for a log line (for filters)."""
    m = _LEVEL.search(line or "")
    if not m:
        return "ERROR" if _TRACEBACK.match(line or "") else ""
    kind = _LEVEL_KIND.get(m.group(1) or m.group(2), "")
    return {"error": "ERROR", "warning": "WARNING", "info": "INFO", "debug": "DEBUG",
            "ok": "INFO"}.get(kind, "")


def _fmt(color, bold=False, italic=False):
    f = QtGui.QTextCharFormat()
    f.setForeground(QtGui.QColor(color))
    if bold:
        f.setFontWeight(QtGui.QFont.Bold)
    if italic:
        f.setFontItalic(True)
    return f


class LogHighlighter(QtGui.QSyntaxHighlighter):
    """Colour each log line. ``json_mode`` adds key colouring for custody records."""

    def __init__(self, document, json_mode=False):
        super().__init__(document)
        self.json_mode = json_mode
        p = PALETTE
        self.f = {
            "time": _fmt(p["time"]),
            "error": _fmt(p["error"], bold=True),
            "warning": _fmt(p["warning"], bold=True),
            "info": _fmt(p["info"], bold=True),
            "debug": _fmt(p["debug"], italic=True),
            "ok": _fmt(p["ok"], bold=True),
            "logger": _fmt(p["logger"]),
            "tag": _fmt(p["tag"]),
            "path": _fmt(p["path"]),
            "number": _fmt(p["number"]),
            "string": _fmt(p["string"]),
            "hash": _fmt(p["hash"]),
            "key": _fmt(p["key"], bold=True),
            "error_line": _fmt(p["error"]),
            "warning_line": _fmt("#FDE68A"),
        }

    def highlightBlock(self, text):
        if not text:
            return
        # Whole-line tint first, so a warning or error line reads as one at a
        # glance; tokens below paint over it.
        lvl = level_of(text)
        if lvl == "ERROR":
            self.setFormat(0, len(text), self.f["error_line"])
        elif lvl == "WARNING":
            self.setFormat(0, len(text), self.f["warning_line"])

        for m in _NUMBER.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), self.f["number"])
        for m in _TAG.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), self.f["tag"])
        for m in _STRING.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), self.f["string"])
        for m in _PATH.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), self.f["path"])
        for m in _HASH.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), self.f["hash"])
        if self.json_mode:
            m = _JSON_KEY.match(text)
            if m:
                self.setFormat(m.start(1), m.end(1) - m.start(1), self.f["key"])
        m = _LOGGER.search(text)
        if m:
            self.setFormat(m.start(1), m.end(1) - m.start(1), self.f["logger"])
        m = _TS.match(text)
        if m:
            self.setFormat(m.start(1), m.end(1) - m.start(1), self.f["time"])
        m = _LEVEL.search(text)
        if m:
            kind = _LEVEL_KIND.get(m.group(1) or m.group(2), "")
            if kind:
                self.setFormat(m.start(), m.end() - m.start(), self.f[kind])
        if _TRACEBACK.match(text):
            self.setFormat(0, len(text), self.f["error"])


def filter_lines(text, level):
    """Keep lines at ``level`` ('ALL', 'WARNING' = warnings and errors, 'ERROR')."""
    if level in (None, "", "ALL"):
        return text
    keep = ("ERROR",) if level == "ERROR" else ("ERROR", "WARNING")
    return "\n".join(l for l in text.splitlines() if level_of(l) in keep)
