"""System tray icon with the main menu."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QIcon, QPixmap, QPainter, QColor, QFont
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QApplication

from .paths import find_logo


def _fallback_icon() -> QIcon:
    """Generate a simple 'S' badge icon when no logo asset is present."""
    pix = QPixmap(64, 64)
    pix.fill(QColor(40, 110, 220))
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QColor("white"))
    f = QFont()
    f.setBold(True)
    f.setPointSize(36)
    p.setFont(f)
    from PySide6.QtCore import Qt as _Qt
    p.drawText(pix.rect(), _Qt.AlignCenter, "S")
    p.end()
    return QIcon(pix)


def app_icon() -> QIcon:
    logo = find_logo()
    if logo is not None:
        return QIcon(str(logo))
    return _fallback_icon()


class Tray(QObject):
    """Wraps QSystemTrayIcon and emits high-level menu signals."""

    capture_area = Signal()
    capture_fullscreen = Signal()
    capture_window = Signal()
    capture_scroll = Signal()
    capture_delay = Signal()
    color_picker = Signal()
    open_history = Signal()
    open_settings = Signal()
    open_save_dir = Signal()
    quit_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._tray = QSystemTrayIcon(app_icon())
        self._tray.setToolTip("snaplab")
        self._build_menu()
        self._tray.activated.connect(self._on_activated)

    def _build_menu(self) -> None:
        menu = QMenu()

        capture_menu = menu.addMenu("캡처")
        self._add(capture_menu, "영역 캡처", self.capture_area)
        self._add(capture_menu, "전체 화면", self.capture_fullscreen)
        self._add(capture_menu, "활성 창", self.capture_window)
        self._add(capture_menu, "브라우저 스크롤 (전체 페이지)", self.capture_scroll)
        capture_menu.addSeparator()
        self._add(capture_menu, "딜레이 캡처", self.capture_delay)

        menu.addSeparator()
        self._add(menu, "컬러 피커", self.color_picker)
        self._add(menu, "히스토리…", self.open_history)
        self._add(menu, "저장 폴더 열기", self.open_save_dir)
        menu.addSeparator()
        self._add(menu, "설정…", self.open_settings)
        menu.addSeparator()
        self._add(menu, "종료", self.quit_requested)

        self._tray.setContextMenu(menu)
        self._menu = menu  # keep alive

    def _add(self, menu: QMenu, label: str, signal) -> None:
        act = QAction(label, menu)
        act.triggered.connect(lambda: signal.emit())
        menu.addAction(act)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # Left-click triggers area capture; double-click opens settings.
        if reason == QSystemTrayIcon.Trigger:
            self.capture_area.emit()
        elif reason == QSystemTrayIcon.DoubleClick:
            self.open_settings.emit()

    def show(self) -> None:
        self._tray.show()

    def hide(self) -> None:
        self._tray.hide()

    def notify(self, title: str, message: str) -> None:
        if QSystemTrayIcon.supportsMessages():
            self._tray.showMessage(title, message, app_icon(), 2500)

    def is_supported(self) -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()
