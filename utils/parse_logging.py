"""One frame for every parser run: a start line, its output, a done line.

Most parsers report through ``print()`` - Prefetch, WinLog, Amcache, ShimCache,
the MFT/USN pair, the offline wrappers, about six hundred calls between them.
The stdout tee files those under ``console.log`` with no name on them, and in a
live Parse All they ran in worker processes where nothing was captured at all,
so ``parsers.log`` held almost nothing a parser said.

``artifact_run()`` wraps ONE parser run, at the two places every parser is
called from (``ParserInvoker`` for offline and image runs, the live runner in
``utils/concurrency/standalone_parsers.py``):

* logs ``start: <artifact> (<mode>, <source>)`` and, at the end,
  ``done: <n> records in <t>s, <w> warning(s)`` or ``failed after <t>s: ...``,
  under ``Artifacts_Collectors.run.<artifact>``, so it lands in parsers.log;
* copies every line the parser prints, while it runs, into that logger -
  ``[ERROR]`` / ``[WARNING]`` lines at their level - so the parser's own words
  are in the case log under its name. Only lines printed by the thread that
  runs the parser are taken: the GUI thread keeps printing as before. The
  output still reaches stdout, so the loading dialog and console.log are
  unchanged;
* reports progress events (``start``, ``file``, ``records``, ``now``,
  ``warning``, ``done``) to an optional callback, which the parsing dialog's
  checklist is drawn from. A ``\\r`` progress line becomes a ``now`` event
  instead of a log line, so a progress bar does not write a line per percent.

Child processes have no case logging of their own: ``install_child_logging``
sends their records to the GUI process over the queue the live runner already
uses, and ``Progress_Reporter`` files them there (``forward_log_record``).
"""

import collections
import contextlib
import logging
import re
import sys
import threading
import time

RUN_LOGGER_PREFIX = "Artifacts_Collectors.run"

# Level from the tag a parser prints. The order matters: "[WARNING] Error
# reading x" is a warning, so the explicit tag is checked before the word.
_LEVEL_TAGS = (
    (re.compile(r"^\s*\[(?:ERROR|FAIL|FAILED|FATAL|CRITICAL)\b", re.I), logging.ERROR),
    (re.compile(r"^\s*\[(?:WARN|WARNING|STALE)\b", re.I), logging.WARNING),
    (re.compile(r"^\s*\[[^\]]*\b(?:error|failed)\]", re.I), logging.ERROR),
    (re.compile(r"^\s*\[[^\]]*\bwarning\]", re.I), logging.WARNING),
    (re.compile(r"^\s*(?:error|failed|traceback)\b", re.I), logging.ERROR),
    (re.compile(r"^\s*warning\b", re.I), logging.WARNING),
)
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def line_level(line):
    """The logging level a printed line deserves."""
    for pattern, level in _LEVEL_TAGS:
        if pattern.search(line):
            return level
    return logging.INFO


def clean_line(text):
    """A printed line without colour codes or surrounding blanks."""
    return _ANSI.sub("", text or "").strip()


class ArtifactRun(object):
    """What one parser run has done so far. Handed to the ``with`` body."""

    def __init__(self, artifact, label, logger, progress=None):
        self.artifact = artifact
        self.label = label
        self.logger = logger
        self.records = None
        self.warnings = 0
        self.errors = 0
        self.status = "running"
        self.message = ""
        self.started = time.monotonic()
        self._progress = progress
        self._last_now = 0.0
        # The last warning / error lines the parser printed, traceback
        # included: carried to the Parse Status outcome (they used to stop at
        # parsers.log and the loading dialog's tooltip).
        self.excerpt = collections.deque(maxlen=40)

    @property
    def elapsed(self):
        return time.monotonic() - self.started

    def emit(self, event, **data):
        """Send one progress event; never raises."""
        if self._progress is None:
            return
        try:
            payload = {"artifact": self.artifact, "label": self.label, "event": event,
                       "elapsed": round(self.elapsed, 2)}
            payload.update(data)
            self._progress(payload)
        except Exception:
            pass

    def file(self, path, detail=""):
        """The parser started on ``path`` (a hive, a log, a database)."""
        self.logger.info("reading %s%s", path, (" - " + detail) if detail else "")
        self.emit("file", path=str(path), detail=detail)

    def now(self, text):
        """What the parser is doing at this moment (not logged).

        At most four a second: a progress bar rewrites its line thousands of
        times, and from a worker process each one is a queue message.
        """
        t = time.monotonic()
        if t - self._last_now < 0.25:
            return
        self._last_now = t
        self.emit("now", text=text)

    def set_records(self, count):
        self.records = count
        self.emit("records", records=count)

    def warn(self, message):
        self.warnings += 1
        self.logger.warning(message)
        self.excerpt.append("WARNING  %s" % message)
        self.emit("warning", message=message, warnings=self.warnings)


_CAPTURING = threading.local()   # set while a capture is logging a line


class _PrintCapture(object):
    """stdout/stderr wrapper: copies one thread's printed lines into a logger."""

    def __init__(self, stream, run, thread_id):
        self._stream = stream
        self._run = run
        self._thread = thread_id
        self._buffer = ""
        self._lock = threading.RLock()
        self._in_traceback = False
        # False once its run is over. A capture that something else wrapped
        # meanwhile cannot be taken out of sys.stdout, so it stays in the chain
        # - and kept logging every later line under ITS run: the whole offline
        # USN run was written twice, under run.mft and run.usn.
        self.active = True

    def write(self, text):
        try:
            result = self._stream.write(text) if self._stream is not None else len(text or "")
        except Exception:
            result = len(text or "")
        # _take logs each line. When the handler that receives it writes to
        # this same stream on this same thread - Python's last-resort handler
        # does exactly that when the root logger has no handlers, writing a
        # warning to sys.stderr, which is captured - the nested write used to
        # wait on the lock this thread already held: the parse hung for ever,
        # with no error, on the first warning it printed. A nested write - to
        # this capture or to the other one (stdout vs stderr) - is passed
        # through and not captured again, so a line is logged once.
        if self.active and text and threading.get_ident() == self._thread                 and not getattr(_CAPTURING, "on", False):
            with self._lock:
                _CAPTURING.on = True
                try:
                    self._take(text)
                finally:
                    _CAPTURING.on = False
        return result

    def _take(self, text):
        self._buffer += text
        while True:
            cut = min([i for i in (self._buffer.find("\n"), self._buffer.find("\r")) if i >= 0],
                      default=-1)
            if cut < 0:
                break
            line, sep = self._buffer[:cut], self._buffer[cut]
            self._buffer = self._buffer[cut + 1:]
            raw = _ANSI.sub("", line)
            line = clean_line(line)
            if not line or not set(line) - set("=-_*# "):
                continue                     # blank, or a ===== rule
            if sep == "\r":
                self._run.now(line)          # a progress bar: shown, not logged
                continue
            level = line_level(line)
            # A traceback is ERROR to its last line. Only "Traceback (most
            # recent call last)" used to be: the frames and the exception
            # itself ("sqlite3.IntegrityError: FOREIGN KEY constraint
            # failed") were logged at INFO and left out of every count.
            if line.startswith("Traceback (most recent call last)"):
                self._in_traceback = True
                level = logging.ERROR
            elif self._in_traceback:
                level = logging.ERROR
                if not raw[:1].isspace():
                    self._in_traceback = False   # the exception line ends it
            if level >= logging.ERROR:
                self._run.errors += 1
            elif level == logging.WARNING:
                self._run.warnings += 1
            self._run.logger.log(level, line)
            if level >= logging.WARNING:     # the checklist counts these
                self._run.excerpt.append("%-8s %s" % (logging.getLevelName(level), line))
                self._run.emit("line", text=line, level=logging.getLevelName(level))

    def flush_pending(self):
        with self._lock:
            rest = clean_line(self._buffer)
            self._buffer = ""
        if rest:
            self._run.logger.log(line_level(rest), rest)

    def flush(self):
        try:
            if self._stream is not None:
                self._stream.flush()
        except Exception:
            pass

    def isatty(self):
        return False

    def __getattr__(self, item):
        return getattr(self._stream, item)


@contextlib.contextmanager
def artifact_run(artifact, label=None, source="", mode="", progress=None,
                 capture_prints=True):
    """Frame one parser run; see the module docstring."""
    label = label or artifact
    logger = logging.getLogger("%s.%s" % (RUN_LOGGER_PREFIX, artifact))
    run = ArtifactRun(artifact, label, logger, progress)
    where = ", ".join(p for p in (mode, str(source or "")) if p)
    logger.info("start: %s%s", label, (" (%s)" % where) if where else "")
    run.emit("start", source=str(source or ""), mode=mode)

    captures = []
    if capture_prints:
        tid = threading.get_ident()
        for name in ("stdout", "stderr"):
            current = getattr(sys, name)
            cap = _PrintCapture(current, run, tid)
            setattr(sys, name, cap)
            captures.append((name, current, cap))
    try:
        yield run
    except BaseException as exc:
        run.status = "failed"
        run.message = "%s: %s" % (type(exc).__name__, exc)
        import traceback as _tb
        for ln in _tb.format_exc().strip().splitlines()[-20:]:
            run.excerpt.append("ERROR    %s" % ln)
        raise
    finally:
        for name, original, cap in reversed(captures):
            cap.flush_pending()
            cap.active = False               # a pass-through from now on
            # Only put the old stream back if nobody replaced ours meanwhile.
            if getattr(sys, name) is cap:
                setattr(sys, name, original)
        if run.status == "failed":
            logger.error("failed after %.1fs: %s", run.elapsed, run.message)
            run.emit("done", status="failed", message=run.message,
                     records=run.records, warnings=run.warnings)
        else:
            run.status = "done"
            records = "%s records" % ("{:,}".format(run.records) if run.records is not None else "?")
            logger.info("done: %s, %s in %.1fs, %d warning(s), %d error line(s)",
                        label, records, run.elapsed, run.warnings, run.errors)
            run.emit("done", status="done", records=run.records,
                     warnings=run.warnings, errors=run.errors)


def records_from_result(result):
    """A record count from whatever a parser returned, or None."""
    if result is None:
        return None
    for name in ("records_parsed", "records", "total_records", "record_count", "count"):
        value = result.get(name) if isinstance(result, dict) else getattr(result, name, None)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    # A bare int is an exit code (MFT_Claw / USN_Claw main()), not a count:
    # it used to be logged as "done: MFT, 1 records".
    return None


# --- child processes ---------------------------------------------------------

class _QueueRecordHandler(logging.Handler):
    """Sends records to the GUI process in batches.

    One queue message per record was one round-trip to the manager process
    per printed line; a parser that prints thousands of lines spent more time
    reporting than parsing. Records are sent every 0.2 s or every 200,
    whichever comes first, as one ``log_records`` message - and flushed
    explicitly at the end of each task (``flush_child_logging``), because a
    multiprocessing child exits without running atexit handlers.
    """

    BATCH = 200
    INTERVAL = 0.2

    def __init__(self, message_queue):
        super().__init__(logging.INFO)
        self._queue = message_queue
        self._buffer = []
        self._buffer_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._pump, name="log-forwarder", daemon=True)
        self._thread.start()

    def emit(self, record):
        try:
            item = {"name": record.name, "levelno": record.levelno,
                    "levelname": record.levelname, "msg": record.getMessage(),
                    "created": record.created, "process": record.process}
        except Exception:
            return
        with self._buffer_lock:
            self._buffer.append(item)
            full = len(self._buffer) >= self.BATCH
        if full:
            self.flush()

    def flush(self):
        with self._buffer_lock:
            batch, self._buffer = self._buffer, []
        if not batch:
            return
        try:
            self._queue.put({"type": "log_records", "records": batch})
        except Exception:
            pass

    def _pump(self):
        while not self._stop.wait(self.INTERVAL):
            self.flush()

    def close(self):
        self._stop.set()
        self.flush()
        super().close()


def install_child_logging(message_queue):
    """Send this process's log records to the GUI process. Idempotent.

    Called at the top of every function the live runner executes in another
    process (the runner itself and each pool worker). A worker process runs
    several parsers one after another, so a second call is a no-op.
    """
    root = logging.getLogger()
    if any(isinstance(h, _QueueRecordHandler) for h in root.handlers):
        return
    if root.level == logging.NOTSET or root.level > logging.INFO:
        root.setLevel(logging.INFO)
    root.addHandler(_QueueRecordHandler(message_queue))


def flush_child_logging():
    """Send whatever this process has buffered for the GUI, now."""
    for h in logging.getLogger().handlers:
        if isinstance(h, _QueueRecordHandler):
            h.flush()


def forward_log_records(msg):
    """File a ``log_records`` batch in THIS process's logs."""
    for item in msg.get("records") or []:
        forward_log_record(item)


def forward_log_record(msg):
    """File a record sent by ``install_child_logging`` in THIS process's logs."""
    try:
        created = msg.get("created") or time.time()
        record = logging.makeLogRecord({
            "name": msg.get("name") or "child", "levelno": int(msg.get("levelno") or logging.INFO),
            "levelname": msg.get("levelname") or "INFO", "msg": msg.get("msg") or "",
            "args": None, "created": created, "msecs": (created - int(created)) * 1000,
            "process": msg.get("process")})
        logger = logging.getLogger(record.name)
        if logger.isEnabledFor(record.levelno):
            logger.handle(record)
    except Exception:
        pass
