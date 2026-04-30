"""Banner ad widget — fetches and shows banner from gonggamstudio backend.

Used by editor/window.py to display a 600x60 banner under the captured image,
above the bottom action toolbar.

Design:
- HTTP requests run in daemon background threads (using `requests`)
- Results are marshalled to the Qt main thread via PySide6 Signals (auto-queued
  across threads), so QPixmap / QLabel are only touched on the main thread
- 30-minute file-based cache in user_data_dir() for offline / slow-network fallback
- Click → opens user's default browser via QDesktopServices.openUrl
"""
from __future__ import annotations

import json
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any, Optional

import requests
from PySide6.QtCore import Qt, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import QLabel, QWidget

from .. import __version__
from ..paths import user_data_dir


API_BASE = "https://www.gonggamstudio.co.kr"
APP_CODE = "snaplab"
CACHE_TTL_SEC = 30 * 60
FETCH_TIMEOUT_SEC = 4


def _cache_file() -> Path:
    return user_data_dir() / "banner_cache.json"


def _read_cache(slot: str) -> Optional[dict[str, Any]]:
    try:
        data = json.loads(_cache_file().read_text(encoding="utf-8"))
        entry = data.get(slot)
        if not entry:
            return None
        if time.time() - float(entry.get("fetchedAt", 0)) > CACHE_TTL_SEC:
            return None
        return entry.get("banner")
    except Exception:
        return None


def _write_cache(slot: str, banner: Optional[dict[str, Any]]) -> None:
    try:
        path = _cache_file()
        existing: dict[str, Any] = {}
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                existing = {}
        existing[slot] = {"banner": banner, "fetchedAt": time.time()}
        path.write_text(json.dumps(existing), encoding="utf-8")
    except Exception:
        pass


class BannerWidget(QWidget):
    """600×60 banner advertisement slot.

    States:
      - placeholder: dashed border, "광고주를 모십니다" text
      - loaded     : solid border, banner image, click opens external URL
    """

    # Internal signals — emitted from background threads, received on main thread
    _banner_loaded = Signal(object)         # dict | None
    _image_loaded = Signal(bytes, int)      # image bytes, trackingId

    def __init__(
        self,
        slot_id: str = "main-bottom",
        width: int = 600,
        height: int = 60,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._slot = slot_id
        self._w = width
        self._h = height
        self._current_banner: Optional[dict[str, Any]] = None
        self._impression_reported_for: Optional[int] = None

        self.setFixedSize(width, height)

        # Single QLabel covers the entire widget — used for both placeholder text
        # and (later) the banner image
        self._label = QLabel(self)
        self._label.setGeometry(0, 0, width, height)
        self._label.setAlignment(Qt.AlignCenter)
        self._apply_placeholder_style()
        self._set_placeholder_text()

        # Cross-thread signal wiring (auto QueuedConnection because emit happens
        # from background threads)
        self._banner_loaded.connect(self._on_banner_loaded)
        self._image_loaded.connect(self._on_image_loaded)

        # 1) Show cached banner immediately if fresh
        cached = _read_cache(slot_id)
        if cached:
            self._on_banner_loaded(cached)

        # 2) Fetch fresh data in background (always)
        threading.Thread(target=self._fetch_in_background, daemon=True).start()

    # ---------------- visual state ----------------

    def _apply_placeholder_style(self) -> None:
        self._label.setStyleSheet(
            """
            QLabel {
                background: #14161c;
                border: 1px dashed #2a2d35;
                border-radius: 6px;
                color: #8b8b95;
                font-size: 12px;
                padding: 4px;
            }
            """
        )
        self.setCursor(Qt.ArrowCursor)

    def _apply_loaded_style(self) -> None:
        self._label.setStyleSheet(
            """
            QLabel {
                background: #14161c;
                border: 1px solid #1f2129;
                border-radius: 6px;
            }
            """
        )
        self.setCursor(Qt.PointingHandCursor)

    def _set_placeholder_text(self) -> None:
        self._label.clear()
        self._label.setTextFormat(Qt.RichText)
        self._label.setText(
            f"<div style='line-height:1.3'>"
            f"<div style='font-weight:500;color:#8b8b95;'>광고주를 모십니다</div>"
            f"<div style='font-size:10px;color:#5a5a63;font-family:Consolas,monospace;'>"
            f"{self._slot} · {self._w}×{self._h}</div>"
            f"</div>"
        )
        self._apply_placeholder_style()

    # ---------------- background work ----------------

    def _fetch_in_background(self) -> None:
        try:
            url = (
                f"{API_BASE}/api/banners.php"
                f"?app={urllib.parse.quote(APP_CODE)}"
                f"&slot={urllib.parse.quote(self._slot)}"
                f"&v={urllib.parse.quote(__version__)}"
            )
            r = requests.get(url, timeout=FETCH_TIMEOUT_SEC)
            r.raise_for_status()
            data = r.json()  # dict | None
            _write_cache(self._slot, data)
            self._safe_emit(self._banner_loaded, data)
        except Exception:
            # Network down / server error / parse failure — keep current state
            pass

    def _download_image(self, banner: dict[str, Any]) -> None:
        try:
            r = requests.get(banner["imageUrl"], timeout=FETCH_TIMEOUT_SEC)
            r.raise_for_status()
            self._safe_emit(self._image_loaded, r.content, int(banner["trackingId"]))
        except Exception:
            pass

    def _report_impression(self, tracking_id: int) -> None:
        try:
            requests.post(
                f"{API_BASE}/api/impression.php",
                data={"id": str(tracking_id), "app": APP_CODE},
                timeout=FETCH_TIMEOUT_SEC,
            )
        except Exception:
            pass

    @staticmethod
    def _safe_emit(signal: Signal, *args: Any) -> None:
        # If the widget was destroyed before the bg thread finished, emit can
        # raise RuntimeError — swallow it silently
        try:
            signal.emit(*args)
        except RuntimeError:
            pass

    # ---------------- main-thread slots ----------------

    @Slot(object)
    def _on_banner_loaded(self, banner: Optional[dict[str, Any]]) -> None:
        if not banner:
            self._current_banner = None
            self._set_placeholder_text()
            return
        self._current_banner = banner

        # Report impression once per banner id
        try:
            tracking_id = int(banner.get("trackingId", 0))
        except (TypeError, ValueError):
            tracking_id = 0
        if tracking_id and self._impression_reported_for != tracking_id:
            self._impression_reported_for = tracking_id
            threading.Thread(
                target=self._report_impression, args=(tracking_id,), daemon=True
            ).start()

        # Kick off image download in background
        if banner.get("imageUrl"):
            threading.Thread(
                target=self._download_image, args=(banner,), daemon=True
            ).start()

    @Slot(bytes, int)
    def _on_image_loaded(self, data: bytes, tracking_id: int) -> None:
        # Make sure the loaded image still matches the current banner
        if not self._current_banner:
            return
        try:
            current_id = int(self._current_banner.get("trackingId", 0))
        except (TypeError, ValueError):
            current_id = 0
        if current_id != tracking_id:
            return

        pix = QPixmap()
        if not pix.loadFromData(data):
            return
        scaled = pix.scaled(
            self._w,
            self._h,
            Qt.KeepAspectRatioByExpanding,
            Qt.SmoothTransformation,
        )
        self._label.setPixmap(scaled)
        self._label.setToolTip(self._current_banner.get("altText") or "")
        self._apply_loaded_style()

    # ---------------- click ----------------

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if (
            event.button() == Qt.LeftButton
            and self._current_banner
            and self._current_banner.get("linkUrl")
        ):
            try:
                tracking_id = int(self._current_banner.get("trackingId", 0))
            except (TypeError, ValueError):
                tracking_id = 0
            if tracking_id:
                click_url = (
                    f"{API_BASE}/api/click.php"
                    f"?id={tracking_id}"
                    f"&app={urllib.parse.quote(APP_CODE)}"
                )
                QDesktopServices.openUrl(QUrl(click_url))
                event.accept()
                return
        super().mousePressEvent(event)
