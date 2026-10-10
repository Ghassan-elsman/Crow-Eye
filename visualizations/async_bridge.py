"""Chart bridges that answer off the GUI thread.

Every dashboard's QWebChannel slot ran its SQL on the GUI thread: while a
query ran, nothing in Crow-Eye could paint - the React loading overlay froze
mid-animation and Windows marked the main window "Not Responding". On a large
case that was seconds to minutes per click (MFT/USN overview 21 s, a timeline
day 70 s, an MFT/USN search 97 s).

``AsyncBridge`` is the base the bridges now derive from instead of QObject.
It adds one slot, ``callAsync(method, requestId, argsJson)``: the named slot
runs in a small thread pool and its JSON string comes back through the
``asyncResult(requestId, json)`` signal, on the GUI thread. The page's
``call()`` (react-*/src/bridge.js, react-timeline's useBridge) uses it when it
is there and falls back to the plain synchronous call otherwise - so a
dashboard keeps working unchanged against an older bridge.

Nothing about the slots themselves changes: each still opens its own SQLite
connection per call (connections are thread-bound), and the result caches
are guarded by ``_cache_lock``. Each call's duration and payload size go to
the ``crow_eye.visualizations`` log, which had no timing at all.
"""

import json
import logging
import threading
import time

from PyQt5.QtCore import QObject, QRunnable, QThreadPool, Qt, pyqtSignal, pyqtSlot

logger = logging.getLogger("crow_eye.visualizations")

# Slots that must not run on a worker (they touch widgets or the dialog).
_GUI_ONLY = {"callAsync", "deleteLater", "setParent", "setObjectName"}


def cached_slot(name, db_paths):
    """Decorator (under @pyqtSlot) for a ``(self, args_json)`` slot whose
    answer depends only on its filters and the databases ``db_paths(self)``
    returns: the answer is kept until a filter or a database changes."""
    import functools
    import inspect

    def deco(fn):
        # A bounds slot takes no filters: called as fn(self).
        takes_args = len(inspect.signature(fn).parameters) > 1

        @functools.wraps(fn)
        def wrapper(self, args_json=""):
            compute = (lambda a: fn(self, a)) if takes_args else (lambda _a: fn(self))
            return self.cached_result(name, args_json, compute, db_paths(self))
        return wrapper
    return deco


def _drop_queue(pool):
    try:
        pool.clear()
    except RuntimeError:
        pass                              # the bridge was deleted before its dialog


class _Call(QRunnable):
    def __init__(self, bridge, method, request_id, args):
        super().__init__()
        self.bridge, self.method, self.request_id, self.args = bridge, method, request_id, args
        self.setAutoDelete(True)

    def run(self):
        t0 = time.monotonic()
        try:
            out = getattr(self.bridge, self.method)(*self.args)
            if not isinstance(out, str):
                out = json.dumps(out, default=str)
        except Exception as exc:                                  # reported to the page
            logger.exception("%s.%s failed", type(self.bridge).__name__, self.method)
            # Its own key: a slot may legitimately answer {"error": ...}
            # (timeline getEventDetail); the page turns this one into null,
            # what a synchronous slot that raised gave it.
            out = json.dumps({"__asyncError": "%s: %s" % (type(exc).__name__, exc)})
        took = time.monotonic() - t0
        log = logger.info if took >= 1.0 else logger.debug
        log("%s.%s: %.2f s, %s KB", type(self.bridge).__name__, self.method, took,
            "{:,}".format(len(out) // 1024))
        try:
            self.bridge._finished.emit(self.request_id, out)
        except RuntimeError:
            pass                          # the dialog (and its bridge) closed meanwhile


class AsyncBridge(QObject):
    """QObject base for chart bridges: adds callAsync / asyncResult."""

    asyncResult = pyqtSignal(str, str)
    _finished = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pool = QThreadPool(self)
        # A few at once: a dashboard opens with 3-5 calls, and one slow call
        # (a search over 3.8 M rows) must not hold up the others.
        self._pool.setMaxThreadCount(3)
        self._cache_lock = threading.RLock()
        self._finished.connect(self._deliver, Qt.QueuedConnection)
        # The pool dies with the dialog, and its destructor waits for every
        # queued call too: drop the queue first, so closing a dashboard
        # waits at most for the calls already running.
        if parent is not None:
            parent.destroyed.connect(lambda *_a, p=self._pool: _drop_queue(p))

    @pyqtSlot(str, str)
    def _deliver(self, request_id, payload):
        self.asyncResult.emit(request_id, payload)

    @pyqtSlot(str, str, str)
    def callAsync(self, method, request_id, args_json):
        """Run slot ``method`` off the GUI thread; answer via asyncResult."""
        fn = getattr(self, method, None) if isinstance(method, str) else None
        # Data getters only: anything else (openEventDetailDialog) creates
        # widgets and must run on the GUI thread. The pages apply the same rule.
        if (not method or not method.startswith("get") or method in _GUI_ONLY
                or not callable(fn)):
            self.asyncResult.emit(request_id, json.dumps(
                {"__asyncError": "not callable off the GUI thread: %r" % method}))
            return
        try:
            args = json.loads(args_json) if args_json else []
            if not isinstance(args, list):
                args = [args]
        except ValueError:
            args = [args_json]
        # The page passes exactly the arguments the synchronous call takes.
        self._pool.start(_Call(self, method, request_id, args))

    def cached_result(self, name, args_json, compute, db_paths, limit=48):
        """``compute(args_json)``, kept per filters while the databases are
        unchanged (their mtimes are in the key, so a re-parse refreshes it).
        The answer is computed outside the lock; the cache is touched under it.
        """
        import os
        stamps = []
        for path in db_paths or ():
            try:
                stamps.append(os.path.getmtime(path) if path else None)
            except OSError:
                stamps.append(None)
        try:
            norm = json.dumps(json.loads(args_json or "{}"), sort_keys=True)
        except (ValueError, TypeError):
            norm = str(args_json)
        key = (name, norm, tuple(stamps))
        with self._cache_lock:
            cache = self.__dict__.setdefault("_async_cache", {})
            hit = cache.get(key)
        if hit is not None:
            return hit
        value = compute(args_json)
        with self._cache_lock:
            if len(cache) >= limit:
                cache.clear()
            cache[key] = value
        return value

    def clear_cache(self):
        """Forget every kept answer (tests that change a module constant)."""
        with self._cache_lock:
            self.__dict__.pop("_async_cache", None)

    def wait_for_calls(self, msecs=30000):
        """Tests and dialog shutdown: wait for the calls in flight."""
        return self._pool.waitForDone(msecs)
