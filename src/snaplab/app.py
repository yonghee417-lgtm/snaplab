"""Top-level orchestration.

Owns the QApplication, tray, hotkey manager, settings window, and acts as the
dispatcher for every capture action triggered by hotkeys, tray clicks, or
CLI args.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QMessageBox

from . import APP_NAME, autostart
from .capture import area as area_capture
from .capture import fullscreen as fs_capture
from .capture import scroll as scroll_capture
from .capture import window as win_capture
from .editor.window import EditorWindow
from .features import color_picker, delay, history
from .features.history import HistoryWindow, add_to_history
from .hotkeys import HotkeyManager, bindings_from_settings
from .paths import default_save_dir, find_logo
from .settings import get_settings
from .tray import Tray, app_icon
from .ui.settings_window import SettingsWindow
from .utils.clipboard import copy_image
from .utils.image import expand_filename, save_png


class SnaplabApp(QObject):
    def __init__(self, qapp: QApplication) -> None:
        super().__init__()
        self.qapp = qapp
        self.qapp.setQuitOnLastWindowClosed(False)
        self.qapp.setApplicationName(APP_NAME)
        self.qapp.setOrganizationName(APP_NAME)
        self.qapp.setWindowIcon(app_icon())

        self.settings = get_settings()
        self._editors: list[EditorWindow] = []
        self._overlays: list[object] = []  # area/color overlays kept alive
        self._settings_window: SettingsWindow | None = None
        self._history_window: HistoryWindow | None = None
        self._capture_generation = 0

        self.tray = Tray()
        self.qapp._tray_ref = self.tray  # type: ignore[attr-defined]
        if self.settings.get("tray_enabled"):
            self.tray.show()
        self._wire_tray()

        self.hotkeys = HotkeyManager(self)
        self.hotkeys.triggered.connect(self._on_hotkey)
        self.hotkeys.set_bindings(bindings_from_settings(self.settings))

        # React to live settings edits.
        self.settings.changed.connect(self._on_setting_changed)

        # Sync OS-level autostart on startup so it follows whatever's in settings.
        if bool(self.settings.get("autostart")) != autostart.is_enabled():
            autostart.set_enabled(bool(self.settings.get("autostart")))

    # --- wiring ------------------------------------------------------------

    def _wire_tray(self) -> None:
        self.tray.capture_area.connect(self.do_area)
        self.tray.capture_fullscreen.connect(self.do_fullscreen)
        self.tray.capture_window.connect(self.do_window)
        self.tray.capture_scroll.connect(self.do_scroll)
        self.tray.capture_delay.connect(self.do_delay)
        self.tray.color_picker.connect(self.do_color_picker)
        self.tray.open_history.connect(self.show_history)
        self.tray.open_settings.connect(self.show_settings)
        self.tray.open_save_dir.connect(self._open_save_dir)
        self.tray.quit_requested.connect(self.quit)

    def _on_setting_changed(self, key: str) -> None:
        if key.startswith("hotkey_"):
            self.hotkeys.set_bindings(bindings_from_settings(self.settings))
        elif key == "tray_enabled":
            if self.settings.get("tray_enabled"):
                self.tray.show()
            else:
                self.tray.hide()

    def _on_hotkey(self, action: str) -> None:
        {
            "area": self.do_area,
            "fullscreen": self.do_fullscreen,
            "window": self.do_window,
            "scroll": self.do_scroll,
            "delay": self.do_delay,
            "color_picker": self.do_color_picker,
        }.get(action, lambda: None)()

    # --- actions -----------------------------------------------------------

    def _begin_capture(self) -> int:
        self._capture_generation += 1
        self._close_capture_windows()
        QApplication.processEvents()
        return self._capture_generation

    def _is_current_capture(self, token: int) -> bool:
        return token == self._capture_generation

    def _close_capture_windows(self) -> None:
        for overlay in list(self._overlays):
            try:
                close_all = getattr(overlay, "_close_all", None)
                if callable(close_all):
                    close_all()
                elif hasattr(overlay, "close"):
                    overlay.close()
            except Exception:
                pass
        self._overlays.clear()

        for editor in list(self._editors):
            try:
                editor.close()
            except Exception:
                pass
        self._editors.clear()

    def do_area(self) -> None:
        token = self._begin_capture()
        # Small delay lets the tray menu fully close before we screenshot.
        def go() -> None:
            if not self._is_current_capture(token):
                return
            overlay = area_capture.run(
                on_done=lambda img: self._handle_image(img, token),
                on_cancel=lambda: None,
            )
            self._overlays.append(overlay)
            overlay.destroyed.connect(lambda _=None: self._overlays.remove(overlay) if overlay in self._overlays else None)

        QTimer.singleShot(120, go)

    def do_fullscreen(self) -> None:
        token = self._begin_capture()
        QTimer.singleShot(120, lambda: self._capture_fullscreen(token))

    def do_window(self) -> None:
        token = self._begin_capture()
        QTimer.singleShot(120, lambda: self._capture_window(token))

    def do_scroll(self) -> None:
        token = self._begin_capture()
        try:
            port = int(self.settings.get("browser_debug_port") or 9222)
            img = scroll_capture.capture_full_page(port)
        except scroll_capture.ScrollCaptureError as e:
            QMessageBox.information(None, "스크롤 캡처", str(e))
            return
        self._handle_image(img, token)

    def do_delay(self) -> None:
        token = self._begin_capture()
        seconds = int(self.settings.get("delay_seconds") or 3)
        overlay = delay.run_after(seconds, lambda: self._run_delayed_area(token))
        self._overlays.append(overlay)

    def do_color_picker(self) -> None:
        token = self._begin_capture()
        def go() -> None:
            if not self._is_current_capture(token):
                return
            overlay = color_picker.run()
            self._overlays.append(overlay)
            overlay.destroyed.connect(
                lambda _=None: self._overlays.remove(overlay) if overlay in self._overlays else None
            )

        QTimer.singleShot(80, go)

    def _capture_fullscreen(self, token: int) -> None:
        if self._is_current_capture(token):
            self._handle_image(fs_capture.capture_all(), token)

    def _capture_window(self, token: int) -> None:
        if self._is_current_capture(token):
            self._handle_image(win_capture.capture_active_window(), token)

    def _run_delayed_area(self, token: int) -> None:
        if self._is_current_capture(token):
            self.do_area()

    # --- post-capture pipeline --------------------------------------------

    def _handle_image(self, img: Image.Image, token: int | None = None) -> None:
        if token is not None and not self._is_current_capture(token):
            return
        copied = False
        saved_path: Path | None = None

        if self.settings.get("copy_to_clipboard_after_capture"):
            try:
                copy_image(img)
                copied = True
            except Exception:
                pass

        if self.settings.get("auto_save_after_capture"):
            saved_path = self._save_immediately(img)

        # Always retain in history.
        try:
            add_to_history(img)
        except Exception:
            pass

        if self.settings.get("open_editor_after_capture"):
            self._open_editor(img)
            return

        msg_parts = []
        if copied:
            msg_parts.append("클립보드 복사")
        if saved_path is not None:
            msg_parts.append(f"저장: {saved_path.name}")
        if not msg_parts:
            msg_parts.append("히스토리에 저장됨")
        self.tray.notify("snaplab", " · ".join(msg_parts))

    def _save_immediately(self, img: Image.Image) -> Path | None:
        save_dir = Path(self.settings.get("save_dir") or default_save_dir())
        pattern = self.settings.get("filename_pattern") or "snaplab_{datetime}"
        try:
            return save_png(img, save_dir / (expand_filename(pattern) + ".png"))
        except OSError:
            return None

    def _open_editor(self, img: Image.Image) -> None:
        try:
            from .capture.screen import _log

            _log(f"opening editor for image {img.width}x{img.height}")
            editor = EditorWindow(img)
            _log(
                "editor opened "
                f"zoom={editor._canvas.zoom():.3f} "
                f"canvas={editor._canvas.size().width()}x{editor._canvas.size().height()}"
            )
        except Exception as e:
            try:
                from .capture.screen import _log

                _log(f"editor open failed for image {img.width}x{img.height}: {type(e).__name__}: {e}")
            except Exception:
                pass
            self.tray.notify("snaplab", "편집창을 열지 못했습니다. 캡처 이미지는 클립보드/기록에 보관되었습니다.")
            return
        self._editors.append(editor)
        editor.destroyed.connect(
            lambda _=None: self._editors.remove(editor) if editor in self._editors else None
        )
        editor.show()
        editor.raise_()
        editor.activateWindow()

    # --- windows -----------------------------------------------------------

    def show_settings(self) -> None:
        if self._settings_window is None:
            self._settings_window = SettingsWindow()
            self._settings_window.destroyed.connect(self._on_settings_destroyed)
        self._settings_window.show()
        self._settings_window.raise_()
        self._settings_window.activateWindow()

    def _on_settings_destroyed(self, _=None) -> None:
        self._settings_window = None

    def show_history(self) -> None:
        if self._history_window is None:
            self._history_window = HistoryWindow()
            self._history_window.destroyed.connect(self._on_history_destroyed)
        else:
            self._history_window.refresh()
        self._history_window.show()
        self._history_window.raise_()
        self._history_window.activateWindow()

    def _on_history_destroyed(self, _=None) -> None:
        self._history_window = None

    def _open_save_dir(self) -> None:
        path = Path(self.settings.get("save_dir") or default_save_dir())
        path.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)

    # --- lifecycle ---------------------------------------------------------

    def quit(self) -> None:
        self.hotkeys.stop()
        self.tray.hide()
        # Persist any pending settings before exit (debounced writes).
        try:
            self.settings.flush()
        except Exception:
            pass
        self.qapp.quit()


def run(argv: list[str]) -> int:
    QApplication.setAttribute(Qt.AA_UseSoftwareOpenGL, True)
    qapp = QApplication.instance() or QApplication(argv)

    # Optional asset-driven icon (Windows taskbar).
    if find_logo() is not None:
        QGuiApplication.setWindowIcon(app_icon())

    app = SnaplabApp(qapp)

    # CLI flags for one-shot captures (useful for shortcuts on the desktop).
    if "--capture-area" in argv:
        QTimer.singleShot(200, app.do_area)
    elif "--capture-fullscreen" in argv:
        QTimer.singleShot(200, app.do_fullscreen)
    elif "--capture-window" in argv:
        QTimer.singleShot(200, app.do_window)
    elif "--capture-scroll" in argv:
        QTimer.singleShot(200, app.do_scroll)
    elif "--settings" in argv:
        QTimer.singleShot(200, app.show_settings)

    if not app.tray.is_supported():
        # Fallback: open settings as the main window so users on systems without a tray
        # can still interact.
        app.show_settings()

    return qapp.exec()
