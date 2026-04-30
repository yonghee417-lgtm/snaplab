"""Pin a captured image as a floating, always-on-top window.

Click and drag to move. Mouse wheel resizes. Escape or right-click closes.
"""
from __future__ import annotations

from PIL import Image
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent, QPixmap, QWheelEvent
from PySide6.QtWidgets import QLabel, QWidget


class PinWindow(QWidget):
    def __init__(self, image: Image.Image) -> None:
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        from ..utils.image import pil_to_qpixmap

        self._original = pil_to_qpixmap(image)
        self._scale = 1.0
        self._label = QLabel(self)
        self._label.setPixmap(self._original)
        self.resize(self._original.size())
        self._drag_start: QPoint | None = None

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.LeftButton:
            self._drag_start = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
        elif e.button() == Qt.RightButton:
            self.close()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self._drag_start is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_start)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.LeftButton:
            self._drag_start = None

    def wheelEvent(self, e: QWheelEvent) -> None:
        delta = e.angleDelta().y()
        if delta == 0:
            return
        factor = 1.1 if delta > 0 else 1 / 1.1
        self._scale = max(0.1, min(8.0, self._scale * factor))
        new_w = max(40, int(self._original.width() * self._scale))
        new_h = max(40, int(self._original.height() * self._scale))
        scaled = self._original.scaled(new_w, new_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._label.setPixmap(scaled)
        self._label.resize(scaled.size())
        self.resize(scaled.size())

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.key() == Qt.Key_Escape:
            self.close()
        elif e.key() == Qt.Key_C and e.modifiers() & Qt.ControlModifier:
            from ..utils.clipboard import copy_image
            from ..utils.image import qimage_to_pil

            copy_image(qimage_to_pil(self._original.toImage()))
