"""Case-scoped logging: funnel everything Crow-Eye emits into <case>/logs/.

There is no single place that configured logging before this - every parser and
subsystem set up its own handlers, so a lot went only to the console (and, in the
windowless EXE, to nowhere at all). This installs one case-wide capture on top of
whatever each component already does, so opening a case gives the analyst a
complete, on-disk record under ``<case_root>/logs/`` that the Settings -> Logs
panel can browse.

Two capture paths, because Crow-Eye output arrives two ways:
  * the Python ``logging`` tree - caught by handlers on the ROOT logger (every
    ``getLogger(...)`` propagates there): a combined ``crow_eye.log`` plus a few
    per-component files split by logger-name namespace.
  * bare ``print()`` (several parsers, and the only channel a frozen windowless
    build has) - caught by teeing ``sys.stdout`` / ``sys.stderr`` into
    ``console.log`` while still passing through to the real stream.

Everything here is best-effort: a logging failure must never stop a case from
opening, so the caller guards the import/call and every write swallows its own
errors. ``reset_case_logging()`` undoes it all, so switching cases re-points
cleanly and closing a case stops writing into the old one.
"""

import os
import sys
import logging
import threading
from logging.handlers import RotatingFileHandler

# The combined log, then the per-component splits. Each split keeps only records
# whose logger name starts with one of its prefixes; names that match nothing
# still land in the combined log, so nothing is lost.
#
# **The prefix is the package.** A module that calls
# `getLogger(self.__class__.__name__)` produces a name like
# `DatabaseSearchDialog`, which no prefix here can match, so its records reach
# the combined log and no component file at all - silently, because the combined
# log looks complete. `eye.log` was missing 21 modules that way. Every module in
# a split package uses `getLogger(__name__)`; guarded by
# correlation_engine/tests/test_case_logging.py.
# Parser modules that are also imported from their own folder on sys.path
# (`from Regclaw import ...`, `from MFT_Claw import ...`), where `__name__` has
# no `Artifacts_Collectors.` in front of it. Listed so parsers.log takes them
# either way; test_case_logging checks the list against the folders.
PARSER_MODULES = (
    "A_CJL_LNK_Claw", "Browser_Claw", "Prefetch_claw", "Regclaw", "SRUM_Claw",
    "WinLog_Claw", "amcacheparser", "browser_paths", "live_hive_access",
    "partition_analyzer", "recyclebin_claw", "registry_binary_parser",
    "registry_extra_keys", "registry_hive_cache", "registry_hive_walk", "registry_transaction_log",
    "security_hive", "shimcash_claw", "user_artifact_paths", "user_identity",
    "windows_partition_detector", "offline_parsers",
    # Artifacts_Collectors/MFT and USN journal - not importable as a package.
    "MFT_Claw", "USN_Claw", "mft_usn_correlator",
)

_COMPONENT_FILES = [
    # The three ways evidence comes in from outside a live parse each get their
    # own file - they are what an investigator checks first when an import or an
    # image "did nothing". Their records ALSO reach parsers.log (it takes every
    # collector), so that file stays the complete parser-side record.
    # The importer is reached under three names: its own `OfflineImporter`
    # logger, the package path, and the top-level path the standalone launcher
    # uses.
    ("offline_importer.log", ("OfflineImporter", "Offline_Importer",
                              "Artifacts_Collectors.Offline_Importer")),
    ("crow_claw.log", ("crow_claw", "Artifacts_Collectors.crow_claw")),
    ("image_parsing.log", ("image_parsing", "Forensics_Image_parsing",
                           "Artifacts_Collectors.Forensics_Image_parsing")),
    # crow_eye.parsing: the lines the parsing dialog showed (ui/Loading_dialog).
    ("parsers.log", ("Artifacts_Collectors", "crow_claw", "crow_eye.parsing") + PARSER_MODULES),
    ("timeline.log", ("timeline",)),
    ("visualizations.log", ("visualizations",)),
    ("correlation.log", ("correlation_engine",)),
    # The semantic phase on its own: the settings it ran with, whether the
    # FTS5 prefilter was used, progress per chunk, what it labelled. It is the
    # longest phase of a large run, and in correlation.log it was buried among
    # every other engine line. Its records still reach correlation.log too.
    ("semantic_mapping.log", ("correlation_engine.identity_semantic_phase",
                              "correlation_engine.config.semantic_mapping",
                              "correlation_engine.integration.semantic_mapping_integration")),
    ("eye.log", ("eye",)),
    ("uba.log", ("uba",)),
    ("dynamic_linking.log", ("dynamic_mapping",)),
    # The GUI shell: `ui/` - the dialogs, the search stack, the table widgets -
    # and the main window's phase lines (`crow_eye.main`: a parse started, the
    # tables loaded). The rest of `Crow Eye.py` still reports through print(),
    # which the stdout tee files under console.log ("Console (raw output)").
    ("gui.log", ("ui", "crow_eye.main")),
    # The case-database layer: the loaders, the database manager, discovery and
    # the search engines - what every table in the GUI reads through.
    ("case_data.log", ("data",)),
    # Per-artifact parse outcomes (utils/parse_status.py): parsed, source not
    # found, unsupported, failed - the record behind every empty-table i button.
    ("parse_status.log", ("crow_eye.parse_status",)),
]
_FMT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_MAX_BYTES = 5 * 1024 * 1024
_BACKUPS = 3
# console.log is written through the stdout tee, not a logging handler, so it
# rotates itself: past this size it becomes console.log.1 (.2, .3) and a fresh
# file starts. Before this it grew without limit.
_CONSOLE_MAX_BYTES = 10 * 1024 * 1024

_lock = threading.RLock()
_installed_handlers = []          # root-logger handlers we added
_orig_stdout = None
_orig_stderr = None
_console_tee = None               # the _Tee wrapping stdout (owns the file)
_current_logs_dir = None
_app_handler = None               # the always-on app.log handler


class _PrefixFilter(logging.Filter):
    """Pass only records whose logger name IS a prefix or sits under it.

    The match stops at a dot: `ui` takes `ui.settings_dialog` but not a logger
    that merely begins with the same letters.
    """

    def __init__(self, prefixes):
        super().__init__()
        self._prefixes = tuple(prefixes)

    def filter(self, record):
        name = record.name or ""
        return any(name == p or name.startswith(p + ".") for p in self._prefixes)


class _ConsoleFile:
    """console.log, shared by the stdout and stderr tees, rotating by size."""

    def __init__(self, path, max_bytes=None, backups=_BACKUPS):
        self.path = path
        self.max_bytes = max_bytes or _CONSOLE_MAX_BYTES
        self.backups = backups
        self.lock = threading.Lock()
        self._roll_if_needed()
        self.fh = open(path, "a", encoding="utf-8")

    def _roll_if_needed(self):
        try:
            if os.path.getsize(self.path) < self.max_bytes:
                return
        except OSError:
            return
        for i in range(self.backups - 1, 0, -1):
            src, dst = "%s.%d" % (self.path, i), "%s.%d" % (self.path, i + 1)
            if os.path.exists(src):
                try:
                    os.replace(src, dst)
                except OSError:
                    pass
        try:
            os.replace(self.path, self.path + ".1")
        except OSError:
            pass

    def write(self, text):
        self.fh.write(text)
        self.fh.flush()
        try:
            if self.fh.tell() >= self.max_bytes:
                self.fh.close()
                self._roll_if_needed()
                self.fh = open(self.path, "a", encoding="utf-8")
        except Exception:
            pass

    def flush(self):
        self.fh.flush()

    def close(self):
        self.fh.close()


class _Tee:
    """Write to the original stream (if any) and to a shared log file.

    Robust to ``original is None`` - a frozen windowless build has no real
    stdout, and there the file is the only place the output can go. Attribute
    access delegates to the original stream when present so code that reaches for
    ``fileno()``/``isatty()`` still works; a handful of essentials are provided
    directly for the None case.
    """

    def __init__(self, original, fh, file_lock):
        self._original = original
        self._fh = fh               # a _ConsoleFile (or any file-like object)
        self._lock = file_lock

    def write(self, text):
        if self._original is not None:
            try:
                self._original.write(text)
            except Exception:
                pass
        try:
            with self._lock:
                self._fh.write(text)
                self._fh.flush()
        except Exception:
            pass
        return len(text) if text else 0

    def flush(self):
        for target in (self._original, self._fh):
            try:
                if target is not None:
                    target.flush()
            except Exception:
                pass

    def isatty(self):
        try:
            return bool(self._original) and self._original.isatty()
        except Exception:
            return False

    def fileno(self):
        if self._original is not None:
            return self._original.fileno()
        raise OSError("no fileno on a headless console tee")

    def __getattr__(self, item):
        # Only reached for attributes not defined above.
        if self._original is not None:
            return getattr(self._original, item)
        raise AttributeError(item)


def _make_handler(path, prefixes=None):
    h = RotatingFileHandler(path, maxBytes=_MAX_BYTES, backupCount=_BACKUPS,
                            encoding="utf-8", delay=True)
    h.setFormatter(logging.Formatter(_FMT))
    h.setLevel(logging.INFO)
    if prefixes:
        h.addFilter(_PrefixFilter(prefixes))
    h._crow_eye_case = True       # tag so reset can find and remove it
    return h


def app_logs_dir():
    """Where the always-on application log lives, outside any case.

    `%LOCALAPPDATA%/Crow-Eye/logs` on Windows, `~/.crow-eye/logs` elsewhere. It
    is deliberately not the install directory: a packaged Crow-Eye may sit
    somewhere the user cannot write, and a log that fails to open silently is
    worse than no log.
    """
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    name = "Crow-Eye" if os.environ.get("LOCALAPPDATA") else ".crow-eye"
    return os.path.join(base, name, "logs")


def configure_app_logging():
    """Start capturing before any case exists. Idempotent.

    Case logging only begins when a case is opened, so everything before that -
    startup, the dependency bootstrap, the startup menu, and any crash on the
    way - went to a console that a windowless build does not have. This installs
    one always-on handler so that output has somewhere to land, and the case
    handlers layer on top of it rather than replacing it.

    Returns the log file path, or None if it could not be set up.
    """
    global _app_handler
    with _lock:
        if _app_handler is not None:
            return getattr(_app_handler, "baseFilename", None)
        try:
            d = app_logs_dir()
            os.makedirs(d, exist_ok=True)
            path = os.path.join(d, "app.log")
            h = RotatingFileHandler(path, maxBytes=_MAX_BYTES,
                                    backupCount=_BACKUPS, encoding="utf-8",
                                    delay=True)
            h.setFormatter(logging.Formatter(_FMT))
            h.setLevel(logging.INFO)
            h._crow_eye_app = True     # NOT _crow_eye_case: reset must not remove it
            root = logging.getLogger()
            if root.level == logging.NOTSET or root.level > logging.INFO:
                root.setLevel(logging.INFO)
            root.addHandler(h)
            _app_handler = h
            logging.getLogger(__name__).info("App logging -> %s", path)
            return path
        except Exception as exc:
            logging.getLogger(__name__).debug("cannot set up app logging: %s", exc)
            return None


def configure_case_logging(case_root):
    """Point Crow-Eye's logging at ``<case_root>/logs/``. Idempotent per case.

    Returns the logs directory, or None if it could not be set up (the caller
    treats that as "logging stays as it was" and carries on).
    """
    global _orig_stdout, _orig_stderr, _console_tee, _current_logs_dir
    if not case_root:
        return None
    with _lock:
        reset_case_logging()      # never stack two cases' handlers
        try:
            logs_dir = os.path.join(case_root, "logs")
            os.makedirs(logs_dir, exist_ok=True)
        except Exception as exc:
            logging.getLogger(__name__).debug("cannot create logs dir: %s", exc)
            return None

        root = logging.getLogger()
        if root.level == logging.NOTSET or root.level > logging.INFO:
            root.setLevel(logging.INFO)

        try:
            combined = _make_handler(os.path.join(logs_dir, "crow_eye.log"))
            root.addHandler(combined)
            _installed_handlers.append(combined)
            for fname, prefixes in _COMPONENT_FILES:
                h = _make_handler(os.path.join(logs_dir, fname), prefixes)
                root.addHandler(h)
                _installed_handlers.append(h)
        except Exception as exc:
            logging.getLogger(__name__).debug("cannot add file handlers: %s", exc)

        # Console tee -> console.log, capturing print()-only output.
        try:
            fh = _ConsoleFile(os.path.join(logs_dir, "console.log"))
            file_lock = fh.lock
            _orig_stdout, _orig_stderr = sys.stdout, sys.stderr
            _console_tee = _Tee(_orig_stdout, fh, file_lock)
            sys.stdout = _console_tee
            sys.stderr = _Tee(_orig_stderr, fh, file_lock)
        except Exception as exc:
            logging.getLogger(__name__).debug("cannot tee console: %s", exc)

        _current_logs_dir = logs_dir
        logging.getLogger(__name__).info("Case logging -> %s", logs_dir)
        return logs_dir


def reset_case_logging():
    """Remove the case handlers and restore stdout/stderr. Safe to call anytime."""
    global _orig_stdout, _orig_stderr, _console_tee, _current_logs_dir
    with _lock:
        root = logging.getLogger()
        for h in list(_installed_handlers):
            try:
                root.removeHandler(h)
                h.close()
            except Exception:
                pass
        _installed_handlers.clear()

        # Restore the streams only if we are still the ones in place (do not clobber
        # a tee some other code may have installed after us).
        if _console_tee is not None:
            try:
                if sys.stdout is _console_tee and _orig_stdout is not None:
                    sys.stdout = _orig_stdout
                if isinstance(sys.stderr, _Tee) and _orig_stderr is not None:
                    sys.stderr = _orig_stderr
            except Exception:
                pass
            try:
                _console_tee._fh.close()
            except Exception:
                pass
        _orig_stdout = _orig_stderr = _console_tee = None
        _current_logs_dir = None


def current_logs_dir():
    """The active case's logs directory, or None."""
    return _current_logs_dir
