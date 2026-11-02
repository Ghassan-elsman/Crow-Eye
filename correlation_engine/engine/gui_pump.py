"""Keep the window painting during long work - from the GUI thread only.

The engines and the semantic phase run on worker threads in the app and on
the GUI thread from scripts and tests. `QApplication.processEvents()` from a
worker thread runs the GUI's events on the wrong thread (Qt does not allow
it); on the GUI thread it is what keeps the window alive. This does the one
and skips the other, and does nothing without a Qt application.
"""


def pump_gui():
    try:
        from PyQt5.QtCore import QCoreApplication, QThread
    except Exception:
        return
    app = QCoreApplication.instance()
    if app is None:
        return
    try:
        if QThread.currentThread() is app.thread():
            app.processEvents()
    except Exception:
        pass
