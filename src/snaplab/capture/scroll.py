"""Full-page browser screenshot via Chrome DevTools Protocol.

Requires the user's Chrome/Edge to be launched with the remote debugging port
enabled, e.g.:

    chrome.exe --remote-debugging-port=9222

We list tabs over HTTP, attach to the active page over WebSocket, then call
`Page.captureScreenshot` with `captureBeyondViewport: true` to get the full
page in one shot — no manual scrolling, no stitching.
"""
from __future__ import annotations

import base64
import json
from io import BytesIO

import requests
import websocket  # websocket-client
from PIL import Image


class ScrollCaptureError(Exception):
    pass


def _list_targets(port: int) -> list[dict]:
    try:
        resp = requests.get(f"http://127.0.0.1:{port}/json", timeout=2)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise ScrollCaptureError(
            "브라우저 디버그 포트에 연결할 수 없습니다.\n"
            "Chrome/Edge를 `--remote-debugging-port=" + str(port) + "` 옵션으로 실행해주세요.\n"
            "(설정 > 브라우저 캡처에서 자세한 안내를 확인할 수 있습니다.)"
        ) from e
    return resp.json()


def _pick_active_page(targets: list[dict]) -> dict:
    pages = [t for t in targets if t.get("type") == "page" and not t.get("url", "").startswith("devtools://")]
    if not pages:
        raise ScrollCaptureError("열린 페이지를 찾을 수 없습니다.")
    # CDP returns the active tab first in most builds; if not, prefer the one
    # whose `url` is http(s) and not chrome://.
    for t in pages:
        url = t.get("url", "")
        if url.startswith(("http://", "https://", "file://")):
            return t
    return pages[0]


class _CDP:
    def __init__(self, ws_url: str) -> None:
        self.ws = websocket.create_connection(ws_url, timeout=30)
        self._id = 0

    def call(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        msg_id = self._id
        self.ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
        # Drain until matching id arrives. Other frames are events we ignore.
        while True:
            raw = self.ws.recv()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if data.get("id") == msg_id:
                if "error" in data:
                    raise ScrollCaptureError(data["error"].get("message", "CDP error"))
                return data.get("result", {})

    def close(self) -> None:
        try:
            self.ws.close()
        except Exception:
            pass


def capture_full_page(port: int = 9222) -> Image.Image:
    """Capture the full scroll height of the active browser tab."""
    target = _pick_active_page(_list_targets(port))
    ws_url = target.get("webSocketDebuggerUrl")
    if not ws_url:
        raise ScrollCaptureError("WebSocket URL을 찾을 수 없습니다 (다른 도구가 디버거에 이미 연결되어 있을 수 있음).")

    cdp = _CDP(ws_url)
    try:
        # Make sure layout is up to date.
        cdp.call("Page.enable")
        # captureBeyondViewport handles the scroll for us; format png keeps quality.
        result = cdp.call(
            "Page.captureScreenshot",
            {
                "format": "png",
                "captureBeyondViewport": True,
                "fromSurface": True,
            },
        )
    finally:
        cdp.close()

    b64 = result.get("data")
    if not b64:
        raise ScrollCaptureError("스크린샷 데이터가 비어 있습니다.")
    return Image.open(BytesIO(base64.b64decode(b64))).convert("RGB")
