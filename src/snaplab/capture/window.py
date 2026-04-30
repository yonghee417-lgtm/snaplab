"""Active-window capture.

Windows: uses GetForegroundWindow + GetWindowRect via pywin32.
macOS / Linux: falls back to pygetwindow's active window rect.
If the OS rect can't be resolved, we capture the primary monitor.
"""
from __future__ import annotations

import sys

from PIL import Image

from . import screen


def _active_rect_windows() -> screen.Rect | None:
    try:
        import win32gui  # type: ignore

        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return None
        try:
            # DWM frame bounds give the visible (drop-shadow-trimmed) rect on
            # Win10+; fall back to GetWindowRect.
            from ctypes import byref, c_int, sizeof, windll
            from ctypes.wintypes import RECT

            DWMWA_EXTENDED_FRAME_BOUNDS = 9
            r = RECT()
            res = windll.dwmapi.DwmGetWindowAttribute(
                c_int(hwnd),
                c_int(DWMWA_EXTENDED_FRAME_BOUNDS),
                byref(r),
                sizeof(r),
            )
            if res == 0:
                return screen.Rect(r.left, r.top, r.right - r.left, r.bottom - r.top)
        except Exception:
            pass
        l, t, r, b = win32gui.GetWindowRect(hwnd)
        return screen.Rect(l, t, r - l, b - t)
    except Exception:
        return None


def _active_rect_generic() -> screen.Rect | None:
    try:
        import pygetwindow as gw

        w = gw.getActiveWindow()
        if w is None:
            return None
        return screen.Rect(int(w.left), int(w.top), int(w.width), int(w.height))
    except Exception:
        return None


def active_window_rect() -> screen.Rect | None:
    if sys.platform == "win32":
        r = _active_rect_windows()
        if r is not None:
            return r
    return _active_rect_generic()


def capture_active_window() -> Image.Image:
    rect = active_window_rect()
    if rect is None or rect.w <= 0 or rect.h <= 0:
        # Fall back to primary monitor.
        mons = screen.monitors()
        rect = mons[0] if mons else screen.virtual_screen_rect()
    # Clamp to virtual desktop bounds (off-screen rects from minimized windows).
    vd = screen.virtual_screen_rect()
    x = max(rect.x, vd.x)
    y = max(rect.y, vd.y)
    w = max(1, min(rect.right, vd.right) - x)
    h = max(1, min(rect.bottom, vd.bottom) - y)
    return screen.grab(screen.Rect(x, y, w, h))
