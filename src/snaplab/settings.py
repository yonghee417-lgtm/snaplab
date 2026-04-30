"""Persistent settings stored as JSON in the user data dir.

Settings are flat; the GUI reads/writes via the typed accessors here.
"""
from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from .paths import default_save_dir, settings_path


_MOD = "cmd" if sys.platform == "darwin" else "ctrl"

DEFAULTS: dict[str, Any] = {
    "hotkey_area": f"<{_MOD}>+<shift>+a",
    "hotkey_fullscreen": f"<{_MOD}>+<shift>+s",
    "hotkey_window": f"<{_MOD}>+<shift>+w",
    "hotkey_scroll": f"<{_MOD}>+<shift>+l",
    "hotkey_color_picker": f"<{_MOD}>+<shift>+c",
    "hotkey_delay": f"<{_MOD}>+<shift>+d",
    "autostart": True,
    "tray_enabled": True,
    "save_dir": str(default_save_dir()),
    "filename_pattern": "snaplab_{date}_{time}",
    "auto_save_after_capture": False,
    "copy_to_clipboard_after_capture": True,
    "open_editor_after_capture": True,
    "delay_seconds": 3,
    "browser_debug_port": 9222,
    "history_max": 10,
    "ocr_languages": "eng+kor",
}


class Settings(QObject):
    """Singleton-ish settings store. Emits `changed(key)` so widgets can react."""

    changed = Signal(str)

    # Coalesce rapid set() calls into a single disk write so dragging a
    # spinner or typing in the hotkey field doesn't hammer the SSD.
    _SAVE_DEBOUNCE_MS = 200

    def __init__(self, path: Path | None = None) -> None:
        super().__init__()
        self._path = path or settings_path()
        self._data: dict[str, Any] = deepcopy(DEFAULTS)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(self._SAVE_DEBOUNCE_MS)
        self._save_timer.timeout.connect(self._save)
        self._dirty = False
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            self._save()
            return
        try:
            loaded = json.loads(self._path.read_text(encoding="utf-8"))
            for k, v in loaded.items():
                if k in DEFAULTS:
                    self._data[k] = v
        except (json.JSONDecodeError, OSError):
            self._save()

    def _save(self) -> None:
        self._dirty = False
        try:
            self._path.write_text(
                json.dumps(self._data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass

    def _schedule_save(self) -> None:
        self._dirty = True
        # Restart the debounce window — a fresh edit pushes the write out
        # by another _SAVE_DEBOUNCE_MS so a burst of edits collapses to one.
        self._save_timer.start()

    def flush(self) -> None:
        """Force pending changes to disk immediately (called on app quit)."""
        if self._dirty:
            self._save_timer.stop()
            self._save()

    def get(self, key: str) -> Any:
        return self._data.get(key, DEFAULTS.get(key))

    def set(self, key: str, value: Any) -> None:
        if self._data.get(key) == value:
            return
        self._data[key] = value
        self._schedule_save()
        self.changed.emit(key)

    def all(self) -> dict[str, Any]:
        return deepcopy(self._data)


_instance: Settings | None = None


def get_settings() -> Settings:
    global _instance
    if _instance is None:
        _instance = Settings()
    return _instance
