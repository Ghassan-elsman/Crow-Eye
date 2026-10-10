"""One "Crow-Eye is working" state for the whole application.

Parsing and loading run behind a deliberately non-modal loading dialog and wait
in nested event loops, so every button and shortcut keeps firing while they
run. Opening the Timeline, a dashboard, Database Search - or worse, another
case - against half-filled tables and databases still being written is how the
GUI crashed. Work sections mark themselves here; feature openers ask before
opening (Crow Eye.py `gated` / `_feature_gate`).

    token = begin("Parsing live artifacts", alive=worker.isRunning)
    ...
    end(token)                      # idempotent

    with busy("Loading case data"):
        ...

    is_busy()  ->  bool
    current()  ->  (reason, elapsed_seconds) of the oldest running section
    when_idle(key, fn)              # run fn once nothing is busy any more

Self-healing: a section registered with `alive` is dropped as soon as that
callable says the work is gone, so a worker that died without calling end()
cannot lock the application. Sections older than MAX_AGE_S are dropped too.
"""

import contextlib
import itertools
import threading
import time

MAX_AGE_S = 6 * 3600
IDLE_DELAY_MS = 300

_lock = threading.RLock()
_ids = itertools.count(1)
_sections = {}          # token -> [reason, started, alive]
_pending = {}           # key -> fn, insertion-ordered
_listeners = []         # called with (busy: bool) when the state flips


def begin(reason, alive=None):
    """Mark work as running. Returns the token to hand to end()."""
    with _lock:
        was = _busy_locked()
        token = next(_ids)
        _sections[token] = [str(reason or "Working"), time.monotonic(), alive]
    if not was:
        _notify(True)
    return token


def end(token):
    """Mark a section finished. Unknown / repeated tokens are ignored."""
    if token is None:
        return
    with _lock:
        if _sections.pop(token, None) is None:
            return
        idle = not _busy_locked()
    if idle:
        _notify(False)
        _schedule_pending()


@contextlib.contextmanager
def busy(reason, alive=None):
    token = begin(reason, alive)
    try:
        yield token
    finally:
        end(token)


def _prune_locked():
    now = time.monotonic()
    for token, (_reason, started, alive) in list(_sections.items()):
        dead = now - started > MAX_AGE_S
        if not dead and alive is not None:
            try:
                dead = not alive()
            except Exception:
                dead = True          # e.g. the worker's C++ object is gone
        if dead:
            _sections.pop(token, None)


def _busy_locked(exclude=None):
    _prune_locked()
    return any(t != exclude for t in _sections)


def is_busy(exclude=None):
    """Is anything running? `exclude` ignores one token - a window asking
    whether OTHER work is running while its own search holds a section."""
    with _lock:
        busy_now = _busy_locked(exclude)
        idle_all = not _sections
    if idle_all and _pending:
        _schedule_pending()          # a pruned section may have been the last
    return busy_now


def current(exclude=None):
    """(reason, elapsed seconds) of the oldest running section, or (None, 0)."""
    with _lock:
        if not _busy_locked(exclude):
            return None, 0.0
        token = min(t for t in _sections if t != exclude)
        reason, started, _alive = _sections[token]
        return reason, time.monotonic() - started


def reasons():
    with _lock:
        _prune_locked()
        return [r for r, _s, _a in (_sections[t] for t in sorted(_sections))]


def sections():
    """[(reason, elapsed seconds)] of every running section, oldest first."""
    with _lock:
        _prune_locked()
        now = time.monotonic()
        return [(_sections[t][0], now - _sections[t][1]) for t in sorted(_sections)]


def when_idle(key, fn):
    """Run `fn` once nothing is busy. One pending action per key - asking
    twice for the Timeline opens it once."""
    with _lock:
        _pending.pop(key, None)
        _pending[key] = fn
    if not is_busy():
        _schedule_pending()


def pending_keys():
    with _lock:
        return list(_pending)


def add_listener(fn):
    """fn(busy: bool) whenever the application goes busy or idle."""
    _listeners.append(fn)


def remove_listener(fn):
    try:
        _listeners.remove(fn)
    except ValueError:
        pass


def _notify(state):
    """Listeners touch widgets, so they run on the GUI thread: queued through
    a zero-delay timer when a Qt application exists, called directly otherwise
    (tests, headless)."""
    for fn in list(_listeners):
        _deliver(fn, state)


_relay = None


def _gui_relay():
    """A QObject living on the GUI thread whose signal is connected QUEUED.

    Emitting it from any thread runs the callable later, on the GUI thread.
    Not QTimer.singleShot(0, context, fn): this PyQt5 build has no context
    overload - it raises TypeError, and a fallback that calls immediately would
    run a listener before begin() has even returned its token."""
    global _relay
    if _relay is not None:
        return _relay
    from PyQt5 import QtCore, QtWidgets
    app = QtWidgets.QApplication.instance()
    if app is None:
        return None

    class _Relay(QtCore.QObject):
        fire = QtCore.pyqtSignal(object)

    relay = _Relay()
    relay.moveToThread(app.thread())
    relay.fire.connect(lambda fn: fn(), QtCore.Qt.QueuedConnection)
    _relay = relay
    return relay


def _deliver(fn, state):
    def call():
        try:
            fn(state)
        except Exception:
            pass
    try:
        relay = _gui_relay()
        if relay is not None:
            relay.fire.emit(call)
            return
    except Exception:
        pass
    call()                           # no Qt (tests, headless)


def _run_pending():
    with _lock:
        if _busy_locked():
            return                   # something started again meanwhile
        items = list(_pending.items())
        _pending.clear()
    for _key, fn in items:
        try:
            fn()
        except Exception as e:
            print("[Busy guard] queued action failed: %s" % e)


def _schedule_pending():
    if not _pending:
        return
    try:
        from PyQt5 import QtCore
        relay = _gui_relay()
        if relay is not None:
            # end() may run on a worker thread, which has no event loop for a
            # timer: hop to the GUI thread first, then wait there.
            relay.fire.emit(lambda: QtCore.QTimer.singleShot(IDLE_DELAY_MS, _run_pending))
            return
    except Exception:
        pass
    _run_pending()                   # no Qt (tests, headless): run now


def reset():
    """Forget everything - tests only."""
    with _lock:
        _sections.clear()
        _pending.clear()


def format_elapsed(seconds):
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return "%d:%02d:%02d" % (h, m, s) if h else "%02d:%02d" % (m, s)
