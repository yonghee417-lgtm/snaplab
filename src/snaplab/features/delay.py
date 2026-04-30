"""Delay timer: fires a callable after N seconds with a small countdown overlay."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter
from PySide6.QtWidgets import QWidget


class CountdownOverlay(QWidget):
    """Small frameless badge in the corner showing remaining seconds."""

    def __init__(self, seconds: int, on_done: Callable[[], None]) -> None:
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self._seconds = max(1, int(seconds))
        self._on_done = on_done
        self.resize(120, 120)
        self._reposition()

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _reposition(self) -> None:
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.move(screen.right() - self.width() - 30, screen.top() + 30)

    def _tick(self) -> None:
        self._seconds -= 1
        if self._seconds <= 0:
            self._timer.stop()
            self.close()
            self._on_done()
            return
        self.update()

    def paintEvent(self, _evt) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(0, 0, 0, 200))
        p.setPen(Qt.NoPen)
        p.drawEllipse(self.rect().adjusted(2, 2, -2, -2))
        p.setPen(QColor("white"))
        f = QFont()
        f.setPointSize(36)
        f.setBold(True)
        p.setFont(f)
        p.drawText(self.rect(), Qt.AlignCenter, str(self._seconds))
        p.end()


def run_after(seconds: int, fn: Callable[[], None]) -> CountdownOverlay:
    overlay = CountdownOverlay(seconds, fn)
    overlay.show()
    return overlay
