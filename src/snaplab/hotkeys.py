"""Global hotkey listener bridged to Qt signals.

pynput runs on a background thread; we use queued signals so handlers run on the
GUI thread.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, Signal, Qt, QMetaObject, Q_ARG, Slot
from pynput import keyboard


class HotkeyManager(QObject):
    """Listens for global hotkeys and emits a signal per registered action."""

    triggered = Signal(str)  # emits action name

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._listener: keyboard.GlobalHotKeys | None = None
        self._bindings: dict[str, str] = {}  # action -> hotkey string

    def set_bindings(self, bindings: dict[str, str]) -> None:
        """Replace all bindings. Stops any running listener first."""
        self._bindings = dict(bindings)
        self.restart()

    def restart(self) -> None:
        self.stop()
        self.start()

    def start(self) -> None:
        if not self._bindings:
            return
        mapping: dict[str, Callable[[], None]] = {}
        for action, hotkey in self._bindings.items():
            if not hotkey:
                continue
            try:
                # pynput requires lowercase; we normalize on load.
                mapping[hotkey] = self._make_callback(action)
            except Exception:
                continue
        if not mapping:
            return
        try:
            self._listener = keyboard.GlobalHotKeys(mapping)
            self._listener.start()
        except Exception:
            self._listener = None

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None

    def _make_callback(self, action: str) -> Callable[[], None]:
        def cb() -> None:
            # Marshal back to GUI thread.
            QMetaObject.invokeMethod(
                self,
                "_emit",
                Qt.QueuedConnection,
                Q_ARG(str, action),
            )

        return cb

    @Slot(str)
    def _emit(self, action: str) -> None:
        self.triggered.emit(action)


# Settings keys that hold hotkey strings, mapped to action names.
HOTKEY_KEYS = {
    "hotkey_area": "area",
    "hotkey_fullscreen": "fullscreen",
    "hotkey_window": "window",
    "hotkey_scroll": "scroll",
    "hotkey_color_picker": "color_picker",
    "hotkey_delay": "delay",
}


def bindings_from_settings(settings) -> dict[str, str]:
    out = {}
    for key, action in HOTKEY_KEYS.items():
        v = settings.get(key)
        if isinstance(v, str) and v.strip():
            out[action] = v.strip()
    return out
