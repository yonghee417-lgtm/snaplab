"""Screen color picker.

Freezes the screen with a fullscreen overlay (same trick as area selection),
shows a magnifier under the cursor, and copies the picked HEX/RGB to the
clipboard on click.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QFont,
)
from PySide6.QtWidgets import QApplication, QWidget

from ..capture import screen
from ..utils.image import pil_to_qpixmap, qimage_to_pil
from ..utils.clipboard import copy_text


MAG_RADIUS = 70  # in logical px
ZOOM = 8


class ColorPickerOverlay(QWidget):
    picked = Signal(QColor)
    cancelled = Signal()

    def __init__(self) -> None:
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setMouseTracking(True)
        self.setCursor(Qt.BlankCursor)

        self._screen_rect = screen.virtual_screen_rect()
        self._pil = screen.grab(self._screen_rect)
        self._pixmap = pil_to_qpixmap(self._pil)
        self._screen_maps: list[tuple[QRect, screen.Rect, float, float]] = []
        qt_to_phys = screen.qt_screen_to_monitor_rects()
        logical_union: QRect | None = None
        for qs in QGuiApplication.screens():
            logical = QRect(qs.geometry())
            phys = qt_to_phys.get(qs)
            if phys is None:
                dpr = qs.devicePixelRatio() or 1.0
                phys = screen.Rect(
                    int(round(logical.x() * dpr)),
                    int(round(logical.y() * dpr)),
                    int(round(logical.width() * dpr)),
                    int(round(logical.height() * dpr)),
                )
            sx = phys.w / max(1, logical.width())
            sy = phys.h / max(1, logical.height())
            self._screen_maps.append((logical, phys, sx, sy))
            logical_union = QRect(logical) if logical_union is None else logical_union.united(logical)
        if logical_union is None:
            logical_union = QRect(
                self._screen_rect.x,
                self._screen_rect.y,
                self._screen_rect.w,
                self._screen_rect.h,
            )
        self._logical_origin = QPoint(logical_union.x(), logical_union.y())
        self._screen_maps = [
            (r.translated(-self._logical_origin), p, sx, sy)
            for r, p, sx, sy in self._screen_maps
        ]
        self.setGeometry(logical_union)
        self._cursor_pos = QPoint(0, 0)

    def paintEvent(self, _evt) -> None:
        p = QPainter(self)
        for logical, phys, _sx, _sy in self._screen_maps:
            src = QRect(
                phys.x - self._screen_rect.x,
                phys.y - self._screen_rect.y,
                phys.w,
                phys.h,
            )
            p.drawPixmap(logical, self._pixmap, src)
        self._draw_loupe(p)
        p.end()

    def _color_at(self, pos: QPoint) -> QColor:
        x, y = self._physical_from_pos(pos)
        x = max(0, min(self._pil.width - 1, x))
        y = max(0, min(self._pil.height - 1, y))
        r, g, b = self._pil.getpixel((x, y))[:3]
        return QColor(r, g, b)

    def _physical_from_pos(self, pos: QPoint) -> tuple[int, int]:
        for logical, phys, sx, sy in self._screen_maps:
            if logical.contains(pos):
                x = phys.x - self._screen_rect.x + int(round((pos.x() - logical.x()) * sx))
                y = phys.y - self._screen_rect.y + int(round((pos.y() - logical.y()) * sy))
                return x, y
        return pos.x(), pos.y()

    def _draw_loupe(self, p: QPainter) -> None:
        pos = self._cursor_pos
        if pos.isNull():
            return
        # Source area in physical pixels.
        src_size = MAG_RADIUS * 2 // ZOOM
        px, py = self._physical_from_pos(pos)
        sx = px - src_size // 2
        sy = py - src_size // 2
        src_rect = QRect(sx, sy, src_size, src_size)

        # Position the loupe to the right of the cursor (or left near edges).
        offset = 20
        cx = pos.x() + offset + MAG_RADIUS
        cy = pos.y() + offset + MAG_RADIUS
        if cx + MAG_RADIUS > self.width():
            cx = pos.x() - offset - MAG_RADIUS
        if cy + MAG_RADIUS > self.height():
            cy = pos.y() - offset - MAG_RADIUS

        target = QRect(cx - MAG_RADIUS, cy - MAG_RADIUS, MAG_RADIUS * 2, MAG_RADIUS * 2)

        # Mask to circle.
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        path_clip = QRect(target)
        p.setClipRect(path_clip)
        p.drawPixmap(target, self._pixmap, src_rect)
        p.restore()

        pen = QPen(QColor(255, 255, 255), 2)
        p.setPen(pen)
        p.drawRect(target)
        # Center crosshair pointing at the picked pixel.
        p.setPen(QPen(QColor(0, 0, 0, 200), 1))
        p.drawLine(cx - 6, cy, cx + 6, cy)
        p.drawLine(cx, cy - 6, cx, cy + 6)

        # Color readout under the loupe.
        col = self._color_at(pos)
        text = f"{col.name().upper()}  rgb({col.red()},{col.green()},{col.blue()})"
        f = QFont()
        f.setPointSize(10)
        f.setBold(True)
        p.setFont(f)
        readout_rect = QRect(target.x(), target.bottom() + 6, target.width(), 22)
        p.fillRect(readout_rect, QColor(0, 0, 0, 200))
        p.setPen(QColor("white"))
        p.drawText(readout_rect, Qt.AlignCenter, text)

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        self._cursor_pos = e.position().toPoint()
        self.update()

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.LeftButton:
            col = self._color_at(e.position().toPoint())
            self.picked.emit(col)
            self.close()
        elif e.button() == Qt.RightButton:
            self._cancel()

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.key() == Qt.Key_Escape:
            self._cancel()

    def _cancel(self) -> None:
        self.cancelled.emit()
        self.close()


def run() -> ColorPickerOverlay:
    overlay = ColorPickerOverlay()

    def on_pick(col: QColor) -> None:
        copy_text(col.name())
        # Notify if any tray is alive.
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None and hasattr(app, "_tray_ref"):
            try:
                app._tray_ref.notify("색상 복사됨", f"{col.name().upper()} (rgb {col.red()},{col.green()},{col.blue()})")
            except Exception:
                pass

    overlay.picked.connect(on_pick)
    overlay.show()  # geometry already covers the virtual desktop
    overlay.raise_()
    overlay.activateWindow()
    overlay.setFocus()
    return overlay
