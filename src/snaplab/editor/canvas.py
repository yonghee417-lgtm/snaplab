"""Graphics-view based editing canvas.

The captured image is kept as a PIL image at full resolution for save/copy.
The on-screen editor is a QGraphicsView scene: the base image is split into
small pixmap tiles and annotations are painted by a lightweight overlay item.
This avoids the large QWidget backing-store path that was failing on wide 4K
captures.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import atan2, cos, pi, sin
from typing import Literal

from PIL import Image
from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QFont,
    QImage,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QTransform,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsItem,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QTextEdit,
)

from ..utils.image import pil_to_qimage, qimage_to_pil

ToolName = Literal["select", "rect", "ellipse", "arrow", "pen", "text", "mosaic", "highlight"]


@dataclass
class Style:
    color: QColor = field(default_factory=lambda: QColor(232, 60, 60))
    width: int = 3


@dataclass
class Annotation:
    kind: ToolName
    style: Style
    p1: QPoint
    p2: QPoint
    points: list[QPoint] = field(default_factory=list)
    text: str = ""
    font_family: str = "Malgun Gothic"
    font_size: int = 24
    text_align: str = "left"


class _AnnotationLayer(QGraphicsItem):
    def __init__(self, canvas: "Canvas") -> None:
        super().__init__()
        self._canvas = canvas
        self.setZValue(10)

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self._canvas._img_w, self._canvas._img_h)

    def paint(self, painter: QPainter, _option, _widget=None) -> None:
        painter.setRenderHint(QPainter.Antialiasing, True)
        self._canvas._paint_annotations(painter, include_in_progress=True)


class Canvas(QGraphicsView):
    image_changed = Signal()
    text_selection_changed = Signal(object)
    zoom_changed = Signal(float)

    def __init__(self, pil_image: Image.Image, parent=None) -> None:
        super().__init__(parent)
        self._base = pil_image.convert("RGB")
        self._img_w = self._base.width
        self._img_h = self._base.height
        self._base_rect = QRect(0, 0, self._img_w, self._img_h)
        self._dpr = 1.0

        self._annotations: list[Annotation] = []
        self._undone: list[Annotation] = []
        self._tool: ToolName = "rect"
        self._style = Style()
        self._mosaic_block = 14
        self._drawing = False
        self._current: Annotation | None = None
        self._selected: Annotation | None = None
        self._drag_mode: str | None = None
        self._drag_offset = QPoint(0, 0)
        self._zoom = 1.0

        self._scene = QGraphicsScene(self)
        self._scene.setSceneRect(0, 0, self._img_w, self._img_h)
        self.setScene(self._scene)
        self._image_tiles = self._make_base_tile_items()
        for item in self._image_tiles:
            self._scene.addItem(item)
        self._layer = _AnnotationLayer(self)
        self._scene.addItem(self._layer)

        self._text_editor = QTextEdit(self.viewport())
        self._text_editor.hide()
        self._text_editor.setFrameShape(QFrame.NoFrame)
        self._text_editor.viewport().setCursor(QCursor(Qt.IBeamCursor))
        self._text_editor.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._text_editor.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._text_editor.textChanged.connect(self._on_inline_text_changed)

        self.setFrameShape(QFrame.NoFrame)
        self.setBackgroundBrush(QBrush(QColor(11, 14, 19)))
        self.setAlignment(Qt.AlignCenter)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setRenderHint(QPainter.SmoothPixmapTransform, False)
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        # NOTE: do NOT call self.viewport().setStyleSheet(...). Qt 6 has a
        # well-documented incompatibility between QGraphicsView's scene
        # rendering and stylesheets applied to the viewport — under
        # high-DPI / large-scene conditions the backing store fails to flush
        # and the entire client area paints as the OS default (light gray).
        # The dark background is provided by setBackgroundBrush above.
        self.setCursor(Qt.CrossCursor)

    # --- public API --------------------------------------------------------

    def image_size(self):
        from PySide6.QtCore import QSize

        return QSize(self._img_w, self._img_h)

    def zoom(self) -> float:
        return self._zoom

    def set_zoom(self, zoom: float) -> None:
        zoom = max(0.05, min(8.0, float(zoom)))
        if abs(self._zoom - zoom) < 0.001:
            return
        self._zoom = zoom
        self.setTransform(QTransform().scale(self._zoom, self._zoom))
        self._sync_text_editor()
        self._layer.update()
        self.viewport().update()
        self.zoom_changed.emit(self._zoom)

    def set_tool(self, t: ToolName) -> None:
        self._tool = t
        self.viewport().setCursor(Qt.CrossCursor if t != "select" else Qt.ArrowCursor)
        if t != "text":
            self._text_editor.hide()

    def set_color(self, c: QColor) -> None:
        self._style.color = c

    def set_width(self, w: int) -> None:
        self._style.width = max(1, w)

    def selected_text_annotation(self) -> Annotation | None:
        if self._selected is not None and self._selected.kind == "text":
            return self._selected
        return None

    def update_selected_text(
        self,
        *,
        text: str | None = None,
        font_family: str | None = None,
        font_size: int | None = None,
        color: QColor | None = None,
        align: str | None = None,
    ) -> None:
        ann = self.selected_text_annotation()
        if ann is None:
            return
        if text is not None:
            ann.text = text
        if font_family is not None:
            ann.font_family = font_family
        if font_size is not None:
            ann.font_size = max(6, int(font_size))
        if color is not None:
            ann.style.color = QColor(color)
        if align is not None:
            ann.text_align = align
        self._refresh()
        self.image_changed.emit()
        self.text_selection_changed.emit(ann)
        self._sync_text_editor()

    def undo(self) -> None:
        if self._annotations:
            self._undone.append(self._annotations.pop())
            self._select_text(None)
            self._refresh()
            self.image_changed.emit()

    def redo(self) -> None:
        if self._undone:
            self._annotations.append(self._undone.pop())
            self._refresh()
            self.image_changed.emit()

    def clear_annotations(self) -> None:
        if not self._annotations:
            return
        self._undone.extend(reversed(self._annotations))
        self._annotations.clear()
        self._select_text(None)
        self._refresh()
        self.image_changed.emit()

    def render_pil(self) -> Image.Image:
        out = QImage(self._img_w, self._img_h, QImage.Format_ARGB32)
        out.setDevicePixelRatio(self._dpr)
        out.fill(Qt.transparent)
        p = QPainter(out)
        p.drawImage(0, 0, pil_to_qimage(self._base))
        self._paint_annotations(p, include_in_progress=False)
        p.end()
        return qimage_to_pil(out).convert("RGB")

    # --- scene / coordinate helpers ---------------------------------------

    def _make_base_tile_items(self) -> list[QGraphicsPixmapItem]:
        items: list[QGraphicsPixmapItem] = []
        tile = 512
        for y in range(0, self._img_h, tile):
            h = min(tile, self._img_h - y)
            for x in range(0, self._img_w, tile):
                w = min(tile, self._img_w - x)
                crop = self._base.crop((x, y, x + w, y + h))
                pix = QPixmap.fromImage(pil_to_qimage(crop))
                item = QGraphicsPixmapItem(pix)
                item.setOffset(x, y)
                item.setZValue(0)
                item.setTransformationMode(Qt.FastTransformation)
                item.setShapeMode(QGraphicsPixmapItem.BoundingRectShape)
                items.append(item)
        return items

    def _refresh(self) -> None:
        # Full-layer invalidate. Used after add/remove/clear when Qt has no
        # way to know which region changed.
        self._layer.update()

    def _refresh_rect(self, rect: QRect | None) -> None:
        """Invalidate just the area an annotation occupies + a small margin
        for line width and arrow heads. Falls back to full refresh if no rect."""
        if rect is None or rect.isNull() or rect.isEmpty():
            self._layer.update()
            return
        # Margin covers thick pens, arrow heads and selection handles.
        margin = max(8, self._style.width * 4)
        r = QRectF(rect.adjusted(-margin, -margin, margin, margin))
        self._layer.update(r)

    def _annotation_bounds(self, a: "Annotation") -> QRect:
        if a.kind == "pen" and a.points:
            xs = [p.x() for p in a.points]
            ys = [p.y() for p in a.points]
            r = QRect(min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1)
        else:
            r = QRect(a.p1, a.p2).normalized()
        return r

    def _to_image_point(self, p: QPoint) -> QPoint:
        scene_pt = self.mapToScene(p)
        x = int(round(scene_pt.x()))
        y = int(round(scene_pt.y()))
        x = max(0, min(self._img_w - 1, x))
        y = max(0, min(self._img_h - 1, y))
        return QPoint(x, y)

    def _scene_rect_to_viewport(self, rect: QRect) -> QRect:
        tl = self.mapFromScene(QPointF(rect.left(), rect.top()))
        br = self.mapFromScene(QPointF(rect.right(), rect.bottom()))
        return QRect(tl, br).normalized()

    # --- painting ----------------------------------------------------------

    def _paint_annotations(self, p: QPainter, include_in_progress: bool) -> None:
        anns = list(self._annotations)
        if include_in_progress and self._current is not None:
            anns.append(self._current)
        for a in anns:
            self._paint_one(p, a)

    def _paint_one(self, p: QPainter, a: Annotation) -> None:
        pen = QPen(a.style.color, a.style.width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        if a.kind == "rect":
            p.drawRect(QRect(a.p1, a.p2).normalized())
        elif a.kind == "ellipse":
            p.drawEllipse(QRect(a.p1, a.p2).normalized())
        elif a.kind == "arrow":
            self._draw_arrow(p, a)
        elif a.kind == "pen":
            if len(a.points) >= 2:
                path = QPainterPath(a.points[0])
                for pt in a.points[1:]:
                    path.lineTo(pt)
                p.drawPath(path)
        elif a.kind == "highlight":
            c = QColor(a.style.color)
            c.setAlpha(90)
            p.setPen(Qt.NoPen)
            p.setBrush(c)
            p.drawRect(QRect(a.p1, a.p2).normalized())
        elif a.kind == "text":
            self._draw_text(p, a)
        elif a.kind == "mosaic":
            self._draw_mosaic(p, a)

    def _draw_arrow(self, p: QPainter, a: Annotation) -> None:
        p.drawLine(a.p1, a.p2)
        dx = a.p2.x() - a.p1.x()
        dy = a.p2.y() - a.p1.y()
        if dx == 0 and dy == 0:
            return
        ang = atan2(dy, dx)
        size = max(10, a.style.width * 4)
        x2, y2 = a.p2.x(), a.p2.y()
        head = QPolygonF(
            [
                a.p2,
                QPoint(int(x2 + size * cos(ang + pi - pi / 7)), int(y2 + size * sin(ang + pi - pi / 7))),
                QPoint(int(x2 + size * cos(ang + pi + pi / 7)), int(y2 + size * sin(ang + pi + pi / 7))),
            ]
        )
        p.setBrush(QBrush(a.style.color))
        p.setPen(Qt.NoPen)
        p.drawPolygon(head)

    def _draw_text(self, p: QPainter, a: Annotation) -> None:
        rect = QRect(a.p1, a.p2).normalized()
        if rect.width() < 4 or rect.height() < 4:
            return
        f = QFont()
        f.setFamily(a.font_family or "Malgun Gothic")
        f.setPointSize(max(6, a.font_size))
        p.setFont(f)
        flags = Qt.TextWordWrap | Qt.AlignVCenter
        if a.text_align == "center":
            flags |= Qt.AlignHCenter
        elif a.text_align == "right":
            flags |= Qt.AlignRight
        else:
            flags |= Qt.AlignLeft
        if not (a is self._selected and self._text_editor.isVisible()):
            p.setPen(a.style.color)
            p.drawText(rect.adjusted(4, 4, -4, -4), flags, a.text)
        if a is self._selected:
            p.save()
            accent = QColor(60, 150, 255)
            p.setPen(QPen(accent, 0, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(rect)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(37, 99, 235, 210))
            p.drawRoundedRect(self._text_move_handle(rect), 3, 3)
            p.setBrush(accent)
            p.drawRect(self._text_resize_handle(rect))
            p.restore()

    def _draw_mosaic(self, p: QPainter, a: Annotation) -> None:
        rect = QRect(a.p1, a.p2).normalized()
        if rect.width() <= 0 or rect.height() <= 0:
            return
        phys_rect = rect.intersected(self._base_rect)
        if phys_rect.isEmpty():
            return
        block = max(4, self._mosaic_block)
        src = self._base.crop(
            (
                phys_rect.x(),
                phys_rect.y(),
                phys_rect.x() + phys_rect.width(),
                phys_rect.y() + phys_rect.height(),
            )
        )
        src_img = pil_to_qimage(src)
        small_w = max(1, phys_rect.width() // block)
        small_h = max(1, phys_rect.height() // block)
        small = src_img.scaled(small_w, small_h, Qt.IgnoreAspectRatio, Qt.FastTransformation)
        big = small.scaled(phys_rect.width(), phys_rect.height(), Qt.IgnoreAspectRatio, Qt.FastTransformation)
        p.drawImage(rect.topLeft(), big)

    # --- text editor -------------------------------------------------------

    def _new_text_annotation(self, pt: QPoint) -> Annotation:
        rect = QRect(pt, QPoint(pt.x() + 360, pt.y() + 120)).intersected(self._base_rect)
        if rect.width() < 40:
            rect.setWidth(40)
        if rect.height() < 30:
            rect.setHeight(30)
        return Annotation(
            "text",
            Style(QColor(self._style.color), self._style.width),
            rect.topLeft(),
            rect.bottomRight(),
            text="텍스트",
        )

    def _select_text(self, ann: Annotation | None) -> None:
        self._selected = ann
        self.text_selection_changed.emit(ann)
        self._sync_text_editor()
        self._refresh()

    def _on_inline_text_changed(self) -> None:
        ann = self.selected_text_annotation()
        if ann is None:
            return
        ann.text = self._text_editor.toPlainText()
        self.text_selection_changed.emit(ann)
        self.image_changed.emit()
        self._refresh()

    def _sync_text_editor(self) -> None:
        ann = self.selected_text_annotation()
        if ann is None or self._tool != "text":
            self._text_editor.hide()
            return
        rect = QRect(ann.p1, ann.p2).normalized()
        view_rect = self._scene_rect_to_viewport(rect)
        self._text_editor.blockSignals(True)
        if self._text_editor.toPlainText() != ann.text:
            self._text_editor.setPlainText(ann.text)
        font = QFont(ann.font_family or "Malgun Gothic", max(6, int(ann.font_size * self._zoom)))
        self._text_editor.setFont(font)
        self._text_editor.setTextColor(ann.style.color)
        self._text_editor.setAlignment(
            Qt.AlignHCenter if ann.text_align == "center" else Qt.AlignRight if ann.text_align == "right" else Qt.AlignLeft
        )
        self._text_editor.setStyleSheet(
            "QTextEdit { background: rgba(15, 23, 34, 90); color: %s; padding: 4px; }"
            % ann.style.color.name()
        )
        move_handle_h = max(14, int(round(16 * self._zoom)))
        editor_rect = view_rect.adjusted(3, move_handle_h + 2, -12, -12)
        if editor_rect.width() < 20 or editor_rect.height() < 20:
            editor_rect = view_rect.adjusted(3, 3, -12, -12)
        self._text_editor.setGeometry(editor_rect)
        self._text_editor.blockSignals(False)
        self._text_editor.show()
        self._text_editor.raise_()
        self._text_editor.setFocus()

    def _text_handle_size(self) -> int:
        return max(10, int(round(14 / max(0.1, self._zoom))))

    def _text_move_handle(self, rect: QRect) -> QRect:
        h = self._text_handle_size()
        return QRect(rect.left(), rect.top(), rect.width(), min(h, rect.height()))

    def _text_resize_handle(self, rect: QRect) -> QRect:
        s = self._text_handle_size()
        return QRect(rect.right() - s + 1, rect.bottom() - s + 1, s, s)

    def _hit_text(self, pt: QPoint) -> tuple[Annotation | None, str | None]:
        for ann in reversed(self._annotations):
            if ann.kind != "text":
                continue
            rect = QRect(ann.p1, ann.p2).normalized()
            if self._text_resize_handle(rect).contains(pt):
                return ann, "resize"
            if self._text_move_handle(rect).contains(pt):
                return ann, "move"
            if rect.contains(pt):
                return ann, None
        return None, None

    def _move_or_resize_text(self, ann: Annotation, pt: QPoint) -> None:
        rect = QRect(ann.p1, ann.p2).normalized()
        if self._drag_mode == "move":
            size = rect.size()
            top_left = pt - self._drag_offset
            top_left.setX(max(0, min(self._img_w - size.width(), top_left.x())))
            top_left.setY(max(0, min(self._img_h - size.height(), top_left.y())))
            ann.p1 = top_left
            ann.p2 = top_left + QPoint(size.width(), size.height())
        elif self._drag_mode == "resize":
            ann.p2 = QPoint(
                max(ann.p1.x() + 40, min(self._img_w - 1, pt.x())),
                max(ann.p1.y() + 30, min(self._img_h - 1, pt.y())),
            )

    # --- input -------------------------------------------------------------

    def wheelEvent(self, e: QWheelEvent) -> None:
        if e.modifiers() & Qt.ControlModifier:
            delta = e.angleDelta().y()
            if delta == 0:
                e.accept()
                return
            scene_pos = self.mapToScene(e.position().toPoint())
            self.set_zoom(self._zoom * (1.15 if delta > 0 else 1 / 1.15))
            new_view_pos = self.mapFromScene(scene_pos)
            view_pos = e.position().toPoint()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + new_view_pos.x() - view_pos.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() + new_view_pos.y() - view_pos.y())
            e.accept()
            return
        super().wheelEvent(e)
        self._sync_text_editor()

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() != Qt.LeftButton:
            super().mousePressEvent(e)
            return
        pt = self._to_image_point(e.position().toPoint())
        if self._tool == "text":
            ann, mode = self._hit_text(pt)
            if ann is not None:
                self._select_text(ann)
                self._drag_mode = mode
                self._drag_offset = pt - ann.p1
                e.accept()
                return
            a = self._new_text_annotation(pt)
            self._annotations.append(a)
            self._undone.clear()
            self._select_text(a)
            self._text_editor.selectAll()
            self.image_changed.emit()
            e.accept()
            return

        if self._selected is not None:
            self._select_text(None)
        self._drawing = True
        style = Style(QColor(self._style.color), self._style.width)
        self._current = Annotation(self._tool, style, pt, pt, points=[pt] if self._tool == "pen" else [])
        self._refresh()
        e.accept()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        pt = self._to_image_point(e.position().toPoint())
        if self._tool == "text" and self._selected is not None and self._drag_mode:
            self._move_or_resize_text(self._selected, pt)
            self._sync_text_editor()
            self._refresh()
            e.accept()
            return
        if self._tool == "text":
            ann, mode = self._hit_text(pt)
            if mode == "resize":
                self.viewport().setCursor(Qt.SizeFDiagCursor)
            elif mode == "move":
                self.viewport().setCursor(Qt.SizeAllCursor)
            elif ann is not None:
                self.viewport().setCursor(Qt.IBeamCursor)
            else:
                self.viewport().setCursor(Qt.CrossCursor)

        if not self._drawing or self._current is None:
            super().mouseMoveEvent(e)
            return
        # Compute pre-update bounds so the previously painted area gets
        # invalidated together with the new one — otherwise the trailing
        # outline of a shrinking shape would stay on screen until the next
        # full repaint.
        old_bounds = self._annotation_bounds(self._current)
        self._current.p2 = self._constrained_point(self._current.p1, pt, self._current.kind, e.modifiers())
        if self._current.kind == "pen":
            self._current.points.append(pt)
        new_bounds = self._annotation_bounds(self._current)
        union = old_bounds.united(new_bounds)
        self._refresh_rect(union)
        e.accept()

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.LeftButton and self._drag_mode:
            self._drag_mode = None
            self._sync_text_editor()
            self.image_changed.emit()
            e.accept()
            return
        if e.button() != Qt.LeftButton or not self._drawing or self._current is None:
            super().mouseReleaseEvent(e)
            return
        self._drawing = False
        pt = self._to_image_point(e.position().toPoint())
        self._current.p2 = self._constrained_point(self._current.p1, pt, self._current.kind, e.modifiers())
        if self._current.kind == "arrow":
            dx = self._current.p2.x() - self._current.p1.x()
            dy = self._current.p2.y() - self._current.p1.y()
            if dx * dx + dy * dy < 9:
                self._current = None
                self._refresh()
                e.accept()
                return
        elif self._current.kind in {"rect", "ellipse", "highlight", "mosaic"}:
            r = QRect(self._current.p1, self._current.p2).normalized()
            if r.width() < 3 or r.height() < 3:
                self._current = None
                self._refresh()
                e.accept()
                return
        self._annotations.append(self._current)
        self._undone.clear()
        self._current = None
        self._refresh()
        self.image_changed.emit()
        e.accept()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._sync_text_editor()

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        super().scrollContentsBy(dx, dy)
        self._sync_text_editor()

    def _constrained_point(self, start: QPoint, end: QPoint, kind: str, modifiers) -> QPoint:
        if not bool(modifiers & Qt.ShiftModifier):
            return end
        dx = end.x() - start.x()
        dy = end.y() - start.y()
        if kind in {"rect", "ellipse"}:
            side = max(abs(dx), abs(dy))
            return QPoint(start.x() + (side if dx >= 0 else -side), start.y() + (side if dy >= 0 else -side))
        if kind == "arrow":
            if abs(dx) >= abs(dy):
                return QPoint(end.x(), start.y())
            return QPoint(start.x(), end.y())
        return end
