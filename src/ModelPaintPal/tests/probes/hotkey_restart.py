"""Run in a subprocess because stale native callbacks can terminate Python."""

import gc
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from PySide6.QtCore import QCoreApplication  # noqa: E402
from app.core.hotkeys import HotkeyManager  # noqa: E402

app = QCoreApplication([])
for index in range(5):
    manager = HotkeyManager()
    manager.set_bindings([('probe', 'Ctrl+Alt+Shift+F24')])
    manager.start()
    listener = manager._thread
    manager.stop()
    assert not listener.is_alive(), 'listener remained alive after immediate stop'
    del manager
    gc.collect()
print('5 immediate native listener stops completed')
