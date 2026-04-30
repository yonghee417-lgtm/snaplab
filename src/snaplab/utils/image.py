"""Image conversions and helpers shared across the app."""
from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path

from PIL import Image
from PySide6.QtGui import QImage, QPixmap


def pil_to_qimage(img: Image.Image) -> QImage:
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    # QPainter on Windows is more reliable with the native 32-bit DIB layout
    # than with Format_RGBA8888, especially for large mixed-DPI captures.
    data = img.tobytes("raw", "BGRA")
    qimg = QImage(data, img.width, img.height, img.width * 4, QImage.Format_ARGB32)
    return qimg.copy()  # detach from data buffer


def pil_to_qimage_rgb(img: Image.Image) -> QImage:
    if img.mode != "RGB":
        img = img.convert("RGB")
    data = img.tobytes("raw", "RGB")
    qimg = QImage(data, img.width, img.height, img.width * 3, QImage.Format_RGB888)
    return qimg.copy()  # detach from data buffer


def pil_to_qpixmap(img: Image.Image) -> QPixmap:
    return QPixmap.fromImage(pil_to_qimage(img))


def qimage_to_pil(qimg: QImage) -> Image.Image:
    qimg = qimg.convertToFormat(QImage.Format_RGBA8888)
    w, h = qimg.width(), qimg.height()
    ptr = qimg.constBits()
    if ptr is None:
        raise ValueError("QImage has no data")
    raw = bytes(ptr)
    return Image.frombuffer("RGBA", (w, h), raw, "raw", "RGBA", 0, 1)


def expand_filename(pattern: str) -> str:
    """Expand `{date}` / `{time}` / `{datetime}` placeholders."""
    now = datetime.now()
    return (
        pattern.replace("{date}", now.strftime("%Y-%m-%d"))
        .replace("{time}", now.strftime("%H-%M-%S"))
        .replace("{datetime}", now.strftime("%Y-%m-%d_%H-%M-%S"))
    )


def save_png(img: Image.Image, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, format="PNG", optimize=False)
    return dest


def png_bytes(img: Image.Image) -> bytes:
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
