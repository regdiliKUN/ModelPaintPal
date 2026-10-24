"""Dispose the shared QApplication before Python module teardown on Windows."""

import atexit
import sys

_installed = False


def _dispose_application():
    widgets = sys.modules.get('PySide6.QtWidgets')
    if widgets is None:
        return
    app = widgets.QApplication.instance()
    if app is None:
        return
    from PySide6.QtCore import QCoreApplication, QEvent, QThreadPool
    from shiboken6 import delete

    QThreadPool.globalInstance().waitForDone(3000)
    app.closeAllWindows()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()
    delete(app)


def install():
    global _installed
    if not _installed:
        atexit.register(_dispose_application)
        _installed = True
