"""Per-monitor area selection with a transparent overlay.

The overlay is translucent — the actual desktop content shows through as-is.
Only the area outside the user's drag selection is dimmed. After release the
overlays are hidden and the selected rect is captured.

This approach avoids any color-space, HDR or screenshot-composite issues
that would otherwise show up when rendering a frozen screenshot under a
mixed-DPI multi-monitor configuration.

Cross-monitor drags are not supported — the selection must complete in the
monitor where it started.
"""
from __future__ import annotations

from typing import Callable

from PIL import Image
from PySide6.QtCore import QObject, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import QApplication, QWidget

from . import screen


DIM_ALPHA = 110  # 0–255; intensity of the dim layer outside the selection


class _MonitorOverlay(QWidget):
    """Frameless translucent overlay covering exactly one monitor."""

    finished = Signal(object)        # screen.Rect, virtual-desktop physical px
    cancelled = Signal()
    enter_capture = Signal()         # Enter pressed — capture full virtual desktop

    def __init__(self, qt_screen, phys_rect=None) -> None:
        super().__init__(
            None,
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool,
        )
        # Translucent surface so the actual screen content is visible underneath.
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setCursor(Qt.CrossCursor)
        self.setMouseTracking(True)

        self._qt_screen = qt_screen
        self._dpr = qt_screen.devicePixelRatio() or 1.0
        g = qt_screen.geometry()
        # Prefer Win32-reported physical rect when available; Qt's
        # geometry()*dpr is unreliable under mixed-DPI multi-monitor.
        if phys_rect is not None:
            self._phys_x, self._phys_y, self._phys_w, self._phys_h = phys_rect
        else:
            self._phys_x = int(round(g.left() * self._dpr))
            self._phys_y = int(round(g.top() * self._dpr))
            self._phys_w = int(round(g.width() * self._dpr))
            self._phys_h = int(round(g.height() * self._dpr))
        # Compute the effective per-monitor scale factor between the overlay
        # widget's logical size and the physical pixel rect we want to address.
        self._scale_x = self._phys_w / max(1, g.width())
        self._scale_y = self._phys_h / max(1, g.height())
        self.setGeometry(g)

        self._origin: QPoint | None = None
        self._end: QPoint | None = None
        self._drag = False
        self._cursor_pos = QPoint(0, 0)

    # --- placement ---------------------------------------------------------

    def showEvent(self, e) -> None:
        super().showEvent(e)
        try:
            wh = self.windowHandle()
            if wh is not None:
                wh.setScreen(self._qt_screen)
                self.setGeometry(self._qt_screen.geometry())
        except Exception:
            pass

    # --- painting ----------------------------------------------------------

    def paintEvent(self, _evt) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        dim = QColor(0, 0, 0, DIM_ALPHA)
        rect = self.rect()
        sel = self._sel_rect()

        if sel is not None and sel.width() > 0 and sel.height() > 0:
            # Dim only the four bands around the selection so the selected
            # region shows live content at full brightness.
            top = QRect(rect.left(), rect.top(), rect.width(), sel.top() - rect.top())
            bottom = QRect(
                rect.left(),
                sel.bottom() + 1,
                rect.width(),
                rect.bottom() - sel.bottom(),
            )
            left = QRect(
                rect.left(),
                sel.top(),
                sel.left() - rect.left(),
                sel.height(),
            )
            right = QRect(
                sel.right() + 1,
                sel.top(),
                rect.right() - sel.right(),
                sel.height(),
            )
            for r in (top, bottom, left, right):
                if r.width() > 0 and r.height() > 0:
                    p.fillRect(r, dim)

            # Two-pass border: dark shadow + bright dashed cyan.
            p.setPen(QPen(QColor(0, 0, 0, 230), 3, Qt.SolidLine))
            p.drawRect(sel.adjusted(0, 0, -1, -1))
            dashed = QPen(QColor(80, 200, 255), 2, Qt.DashLine)
            dashed.setDashPattern([5, 4])
            p.setPen(dashed)
            p.drawRect(sel.adjusted(0, 0, -1, -1))

            # Corner handles.
            handle = 8
            for cx, cy in (
                (sel.left(), sel.top()),
                (sel.right(), sel.top()),
                (sel.left(), sel.bottom()),
                (sel.right(), sel.bottom()),
            ):
                p.fillRect(
                    QRect(cx - handle // 2, cy - handle // 2, handle, handle),
                    QColor(80, 200, 255),
                )

            # Size label (physical pixels).
            phys_w = int(round(sel.width() * self._scale_x))
            phys_h = int(round(sel.height() * self._scale_y))
            label = f"{phys_w} × {phys_h}"
            metrics = p.fontMetrics()
            label_w = metrics.horizontalAdvance(label) + 16
            ly = sel.y() - 26 if sel.y() >= 30 else sel.y() + sel.height() + 4
            p.fillRect(sel.x(), ly, label_w, 22, QColor(0, 0, 0, 220))
            p.setPen(QColor("white"))
            p.drawText(sel.x() + 8, ly + 16, label)
        else:
            # Pre-drag: dim everything and show a crosshair following the cursor.
            p.fillRect(rect, dim)
            cp = self._cursor_pos
            p.setPen(QPen(QColor(80, 200, 255, 200), 1, Qt.DashLine))
            p.drawLine(0, cp.y(), self.width(), cp.y())
            p.drawLine(cp.x(), 0, cp.x(), self.height())

            text = "드래그하여 영역 선택   ·   Esc 취소   ·   Enter 전체화면"
            metrics = p.fontMetrics()
            tw = metrics.horizontalAdvance(text) + 24
            th = metrics.height() + 10
            tx = max(20, (self.width() - tw) // 2)
            ty = 40
            p.fillRect(tx, ty, tw, th, QColor(0, 0, 0, 220))
            p.setPen(QColor("white"))
            p.drawText(tx + 12, ty + th - 8, text)
        p.end()

    def _sel_rect(self) -> QRect | None:
        if self._origin is None or self._end is None:
            return None
        return QRect(self._origin, self._end).normalized()

    # --- input -------------------------------------------------------------

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.LeftButton:
            self._origin = e.position().toPoint()
            self._end = self._origin
            self._drag = True
            self.update()
        elif e.button() == Qt.RightButton:
            self.cancelled.emit()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        self._cursor_pos = e.position().toPoint()
        if self._drag:
            self._end = self._cursor_pos
        self.update()

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        if e.button() != Qt.LeftButton or not self._drag:
            return
        self._drag = False
        self._end = e.position().toPoint()
        sel = self._sel_rect()
        if sel is None or sel.width() < 4 or sel.height() < 4:
            self.cancelled.emit()
            return
        # Convert widget-logical to virtual-desktop physical using the actual
        # per-monitor scale (which may differ from Qt's reported DPR under
        # mixed-DPI setups).
        x = int(round(sel.x() * self._scale_x)) + self._phys_x
        y = int(round(sel.y() * self._scale_y)) + self._phys_y
        w = int(round(sel.width() * self._scale_x))
        h = int(round(sel.height() * self._scale_y))
        self.finished.emit(screen.Rect(x, y, w, h))

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.key() == Qt.Key_Escape:
            self.cancelled.emit()
        elif e.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.enter_capture.emit()


class AreaController(QObject):
    """Owns one transparent overlay per monitor and captures on completion."""

    selected = Signal(Image.Image, object)  # cropped image, screen.Rect
    cancelled = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._overlays: list[_MonitorOverlay] = []
        self._closed = False

        # Diagnostic: log Qt screens vs Win32 monitors so we can see how
        # geometry() and devicePixelRatio() are reported per screen.
        try:
            from . import screen as _scr

            win_rects = _scr._win32_monitor_rects()
            _scr._log(f"Win32 monitor rects (physical): {win_rects}")
            for i, s in enumerate(QGuiApplication.screens()):
                g = s.geometry()
                _scr._log(
                    f"Qt screen[{i}] name={s.name()!r} "
                    f"geometry=({g.left()},{g.top()},{g.width()},{g.height()}) "
                    f"dpr={s.devicePixelRatio()} "
                    f"logicalDPI={s.logicalDotsPerInch()}"
                )
        except Exception:
            pass

        # Build monitor rects via Win32 (physical) and match to Qt screens by
        # primary flag + size. This sidesteps Qt's per-screen geometry which
        # returns inconsistent values under mixed-DPI multi-monitor.
        from . import screen as _scr

        qt_screen_rects = _scr.qt_screen_to_monitor_rects()
        _scr._log(
            "Qt->Win monitor mapping: "
            + str(
                {
                    getattr(qs, "name", lambda: "")(): (
                        rect.x,
                        rect.y,
                        rect.w,
                        rect.h,
                    )
                    for qs, rect in qt_screen_rects.items()
                }
            )
        )
        qt_screens = list(QGuiApplication.screens())
        for qi, qs in enumerate(qt_screens):
            rect = qt_screen_rects.get(qs)
            phys_rect = (
                (rect.x, rect.y, rect.w, rect.h) if rect is not None else None
            )
            ov = _MonitorOverlay(qs, phys_rect)
            ov.finished.connect(self._on_finished)
            ov.cancelled.connect(self._on_cancelled)
            ov.enter_capture.connect(self._on_enter)
            self._overlays.append(ov)
            ov.show()
            ov.raise_()
            ov.activateWindow()
            ov.setFocus()

    def _hide_all(self) -> None:
        for ov in self._overlays:
            ov.hide()
        # Force the window manager to actually take the overlays off-screen
        # before we capture, otherwise they end up in the screenshot.
        QApplication.processEvents()

    def _close_all(self) -> None:
        if self._closed:
            return
        self._closed = True
        for ov in self._overlays:
            ov.close()
        self._overlays.clear()
        self.deleteLater()

    def _on_finished(self, rect: screen.Rect) -> None:
        self._hide_all()
        # Tiny delay so the OS compositor has a chance to repaint without our
        # overlays before bettercam grabs the frame.
        QTimer.singleShot(80, lambda: self._capture(rect))

    def _capture(self, rect: screen.Rect) -> None:
        try:
            img = screen.grab(rect)
        except Exception:
            self._close_all()
            self.cancelled.emit()
            return
        self.selected.emit(img, rect)
        self._close_all()

    def _on_cancelled(self) -> None:
        self.cancelled.emit()
        self._close_all()

    def _on_enter(self) -> None:
        self._hide_all()

        def go() -> None:
            try:
                img = screen.grab_full()
            except Exception:
                self._close_all()
                self.cancelled.emit()
                return
            self.selected.emit(img, screen.virtual_screen_rect())
            self._close_all()

        QTimer.singleShot(80, go)


def run(
    on_done: Callable[[Image.Image], None],
    on_cancel: Callable[[], None] | None = None,
) -> AreaController:
    ctrl = AreaController()
    ctrl.selected.connect(lambda img, _r: on_done(img))
    if on_cancel:
        ctrl.cancelled.connect(on_cancel)
    return ctrl
