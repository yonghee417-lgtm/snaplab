"""Clipboard helpers built on QClipboard."""
from __future__ import annotations

from PIL import Image
from PySide6.QtGui import QClipboard, QGuiApplication

from .image import pil_to_qimage


def copy_image(img: Image.Image) -> None:
    qimg = pil_to_qimage(img)
    QGuiApplication.clipboard().setImage(qimg, QClipboard.Clipboard)


def copy_text(text: str) -> None:
    QGuiApplication.clipboard().setText(text, QClipboard.Clipboard)
