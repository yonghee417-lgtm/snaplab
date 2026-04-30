"""Persistent capture history.

Each capture (after editor close OR direct save) gets dropped into
`<user_data>/history/` as PNG with a sortable filename. The viewer is a simple
grid of thumbnails; clicking opens the file with the OS default viewer.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..paths import history_dir
from ..settings import get_settings
from ..utils.image import expand_filename, pil_to_qimage, save_png


HISTORY_LIMIT = 10
THUMB_SIZE = (160, 120)


def _thumbs_dir() -> Path:
    p = history_dir() / ".thumbs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _load_or_build_thumb(src: Path) -> QPixmap | None:
    """Return a cached thumbnail; rebuild only when the source changed.

    Cache key = source mtime. If source is newer than the cached PNG, regenerate
    once and reuse forever. Stale thumbs are pruned by enforce_limit when the
    parent capture is deleted.
    """
    try:
        cache = _thumbs_dir() / (src.stem + ".png")
        if cache.exists() and cache.stat().st_mtime >= src.stat().st_mtime:
            pix = QPixmap(str(cache))
            if not pix.isNull():
                return pix
        with Image.open(src) as im:
            thumb_img = im.convert("RGB")
            thumb_img.thumbnail(THUMB_SIZE, Image.Resampling.LANCZOS)
            thumb_img.save(cache, format="PNG", optimize=False)
        return QPixmap.fromImage(pil_to_qimage(thumb_img))
    except Exception:
        return None


def _prune_orphan_thumbs() -> None:
    """Drop cached thumbs whose source PNG no longer exists."""
    try:
        thumbs = _thumbs_dir()
        live = {p.stem for p in history_dir().glob("*.png")}
        for t in thumbs.glob("*.png"):
            if t.stem not in live:
                try:
                    t.unlink()
                except OSError:
                    pass
    except Exception:
        pass


def add_to_history(img: Image.Image) -> Path:
    settings = get_settings()
    pattern = settings.get("filename_pattern") or "snaplab_{datetime}"
    path = _unique_history_path(expand_filename(pattern))
    save_png(img, path)
    _enforce_max(HISTORY_LIMIT)
    return path


def _unique_history_path(stem: str) -> Path:
    base = history_dir() / f"{stem}.png"
    if not base.exists():
        return base
    for i in range(1, 1000):
        candidate = history_dir() / f"{stem}_{i:02d}.png"
        if not candidate.exists():
            return candidate
    return history_dir() / f"{stem}_{os.getpid()}.png"


def enforce_limit(limit: int = HISTORY_LIMIT) -> None:
    _enforce_max(limit)


def _enforce_max(limit: int) -> None:
    files = sorted(history_dir().glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[max(1, limit):]:
        try:
            old.unlink()
        except OSError:
            pass
    _prune_orphan_thumbs()


def open_in_os(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
    else:
        subprocess.run(["xdg-open", str(path)], check=False)


class HistoryWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("snaplab — 캡처 기록")
        self.resize(800, 560)
        central = QWidget()
        layout = QVBoxLayout(central)

        self._list = QListWidget()
        self._list.setViewMode(QListWidget.IconMode)
        self._list.setIconSize(QSize(160, 120))
        self._list.setResizeMode(QListWidget.Adjust)
        self._list.setMovement(QListWidget.Static)
        self._list.setSpacing(8)
        self._list.itemDoubleClicked.connect(self._open_item)
        layout.addWidget(self._list)

        actions = QHBoxLayout()
        open_btn = QPushButton("열기")
        open_btn.clicked.connect(self._open_selected)
        copy_btn = QPushButton("클립보드 복사")
        copy_btn.clicked.connect(self._copy_selected)
        delete_btn = QPushButton("삭제")
        delete_btn.clicked.connect(self._delete_selected)
        folder_btn = QPushButton("폴더 열기")
        folder_btn.clicked.connect(lambda: open_in_os(history_dir()))
        actions.addWidget(open_btn)
        actions.addWidget(copy_btn)
        actions.addWidget(delete_btn)
        actions.addStretch(1)
        actions.addWidget(folder_btn)
        layout.addLayout(actions)

        self.setCentralWidget(central)
        self.refresh()

    def refresh(self) -> None:
        enforce_limit()
        self._list.clear()
        files = sorted(history_dir().glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
        for f in files[:HISTORY_LIMIT]:
            thumb = _load_or_build_thumb(f)
            if thumb is None:
                continue
            item = QListWidgetItem(QIcon(thumb), f.name)
            item.setData(Qt.UserRole, str(f))
            self._list.addItem(item)

    def _selected_paths(self) -> list[Path]:
        return [Path(it.data(Qt.UserRole)) for it in self._list.selectedItems()]

    def _open_item(self, item: QListWidgetItem) -> None:
        open_in_os(Path(item.data(Qt.UserRole)))

    def _open_selected(self) -> None:
        for p in self._selected_paths():
            open_in_os(p)

    def _copy_selected(self) -> None:
        paths = self._selected_paths()
        if not paths:
            return
        from ..utils.clipboard import copy_image

        copy_image(Image.open(paths[0]))

    def _delete_selected(self) -> None:
        for p in self._selected_paths():
            try:
                p.unlink()
            except OSError:
                pass
        self.refresh()
