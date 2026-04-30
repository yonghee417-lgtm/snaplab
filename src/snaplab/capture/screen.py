"""Low-level screen grabbing with multi-backend fallback.

Capture chain (Windows):
    1. bettercam — DXGI Desktop Duplication. Captures each output independently
       and composites at Win32-reported monitor positions. Robust under mixed
       DPI / multi-monitor.
    2. mss — fast GDI BitBlt + CAPTUREBLT (fails on some Win11 configs)
    3. PIL.ImageGrab — GDI BitBlt without CAPTUREBLT (renders DirectComposition
       windows as black on some configs)
    4. Qt QScreen.grabWindow — last resort

Other platforms use mss.

Diagnostic log: <user_data>/capture.log.
"""
from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass

from PIL import Image


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    def to_mss(self) -> dict:
        return {"left": self.x, "top": self.y, "width": self.w, "height": self.h}


@dataclass(frozen=True)
class MonitorInfo:
    rect: Rect
    device: str = ""
    primary: bool = False


def _set_windows_dpi_awareness() -> None:
    """Ask Windows for physical pixels on every monitor.

    Qt normally does this, but capture helpers are also used from tests and
    one-shot CLI paths. Calling these APIs repeatedly is harmless; Windows
    simply rejects later calls once awareness is already set.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
        ctypes.windll.user32.SetProcessDpiAwarenessContext(
            DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        )
        return
    except Exception:
        pass
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        import ctypes

        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


_set_windows_dpi_awareness()


# --- debug log -------------------------------------------------------------

def _log(msg: str) -> None:
    try:
        from ..paths import user_data_dir

        with open(user_data_dir() / "capture.log", "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass


# --- Win32 monitor enumeration --------------------------------------------

def _win32_monitor_infos() -> list[MonitorInfo]:
    """Each monitor in virtual-desktop physical pixels."""
    if sys.platform != "win32":
        return []
    try:
        import win32api  # type: ignore
        import win32con  # type: ignore

        out: list[MonitorInfo] = []
        for handle, _hdc, (l, t, r, b) in win32api.EnumDisplayMonitors():
            info = win32api.GetMonitorInfo(handle)
            flags = int(info.get("Flags", 0))
            device = str(info.get("Device", ""))
            out.append(
                MonitorInfo(
                    Rect(int(l), int(t), int(r - l), int(b - t)),
                    device=device,
                    primary=bool(flags & win32con.MONITORINFOF_PRIMARY),
                )
            )
        return out
    except Exception:
        return []


def _win32_monitor_rects() -> list[tuple[int, int, int, int]]:
    """Each monitor's (left, top, width, height) in physical pixels.

    Requires the process to be DPI-aware so positions/sizes are physical. PySide6
    sets per-monitor DPI awareness on import.
    """
    return [(m.rect.x, m.rect.y, m.rect.w, m.rect.h) for m in _win32_monitor_infos()]


# --- mss fallback for monitor info ----------------------------------------

def _mss_monitor_rects() -> list[tuple[int, int, int, int]]:
    import mss as _mss

    with _mss.mss() as sct:
        return [
            (m["left"], m["top"], m["width"], m["height"]) for m in sct.monitors[1:]
        ]


def virtual_screen_rect() -> Rect:
    rects = _win32_monitor_rects() or _mss_monitor_rects()
    if not rects:
        # Conservative fallback.
        return Rect(0, 0, 1920, 1080)
    left = min(x for x, _, _, _ in rects)
    top = min(y for _, y, _, _ in rects)
    right = max(x + w for x, _, w, _ in rects)
    bottom = max(y + h for _, y, _, h in rects)
    return Rect(left, top, right - left, bottom - top)


def monitors() -> list[Rect]:
    rects = _win32_monitor_rects() or _mss_monitor_rects()
    return [Rect(*r) for r in rects]


def _normalize_display_name(name: str) -> str:
    return name.replace("\\\\.\\", "").replace("/", "\\").upper()


def qt_screen_to_monitor_rects() -> dict[object, Rect]:
    """Map QScreen objects to Win32 physical monitor rects.

    Mixed-resolution setups commonly expose Qt geometry in logical pixels while
    capture backends use physical pixels. This helper keeps that conversion in
    one place and avoids relying on enumeration order.
    """
    from PySide6.QtGui import QGuiApplication

    qt_screens = list(QGuiApplication.screens())
    win_infos = _win32_monitor_infos()
    if not qt_screens or not win_infos:
        return {}

    remaining = list(win_infos)
    mapping: dict[object, Rect] = {}

    for qs in qt_screens:
        qname = _normalize_display_name(qs.name())
        match = next(
            (
                m
                for m in remaining
                if qname and qname in _normalize_display_name(m.device)
            ),
            None,
        )
        if match is not None:
            mapping[qs] = match.rect
            remaining.remove(match)

    primary_qt = QGuiApplication.primaryScreen()
    if primary_qt is not None and primary_qt not in mapping:
        match = next((m for m in remaining if m.primary), None)
        if match is not None:
            mapping[primary_qt] = match.rect
            remaining.remove(match)

    for qs in qt_screens:
        if qs in mapping or not remaining:
            continue
        g = qs.geometry()
        center_x = g.left() + g.width() / 2
        center_y = g.top() + g.height() / 2

        def score(m: MonitorInfo) -> float:
            r = m.rect
            mx = r.x + r.w / 2
            my = r.y + r.h / 2
            size_penalty = abs(r.w - g.width()) + abs(r.h - g.height())
            return abs(mx - center_x) + abs(my - center_y) + size_penalty * 0.1

        match = min(remaining, key=score)
        mapping[qs] = match.rect
        remaining.remove(match)

    return mapping


# --- WGC (windows-capture) backend ----------------------------------------

def _windows_capture_frame(monitor_index: int, timeout: float = 2.0) -> Image.Image:
    import windows_capture  # type: ignore

    done = threading.Event()
    result: dict[str, object] = {}
    cap = windows_capture.WindowsCapture(
        cursor_capture=False,
        draw_border=False,
        monitor_index=monitor_index,
    )

    @cap.event
    def on_frame_arrived(frame, control):
        try:
            result["array"] = frame.frame_buffer.copy()
            result["size"] = (int(frame.width), int(frame.height))
        finally:
            control.stop()
            done.set()

    @cap.event
    def on_closed():
        done.set()

    control = cap.start_free_threaded()
    if not done.wait(timeout):
        control.stop()
        control.wait()
        raise TimeoutError(f"WindowsCapture monitor {monitor_index}: no frame")
    control.wait()

    if "array" not in result:
        raise RuntimeError(f"WindowsCapture monitor {monitor_index}: no frame")

    import numpy as np

    arr = result["array"]
    if not isinstance(arr, np.ndarray):
        raise RuntimeError(f"WindowsCapture monitor {monitor_index}: invalid frame")
    # windows-capture returns BGRA.
    rgb = arr[:, :, :3][:, :, ::-1].copy()
    return Image.fromarray(rgb, "RGB")


def _grab_windows_capture(rect: Rect) -> Image.Image:
    monitor_infos = _win32_monitor_infos()
    if not monitor_infos:
        raise RuntimeError("no Win32 monitors found")

    canvas = Image.new("RGB", (rect.w, rect.h), (0, 0, 0))
    used_any = False
    errors: list[str] = []

    for win_idx, monitor in enumerate(monitor_infos):
        mx, my, mw, mh = monitor.rect.x, monitor.rect.y, monitor.rect.w, monitor.rect.h
        ix1 = max(mx, rect.x)
        iy1 = max(my, rect.y)
        ix2 = min(mx + mw, rect.right)
        iy2 = min(my + mh, rect.bottom)
        if ix2 <= ix1 or iy2 <= iy1:
            continue

        monitor_index = win_idx + 1
        try:
            full = _windows_capture_frame(monitor_index)
        except Exception as e:
            errors.append(f"monitor {win_idx}/WindowsCapture {monitor_index}: {e}")
            _log(f"WindowsCapture monitor {win_idx} ({monitor_index}) raised: {e}")
            continue

        if full.size != (mw, mh):
            msg = f"WindowsCapture monitor {win_idx} size {full.size} != win32 ({mw}x{mh})"
            errors.append(msg)
            _log(msg)
            continue

        piece = full.crop((ix1 - mx, iy1 - my, ix2 - mx, iy2 - my))
        canvas.paste(piece, (ix1 - rect.x, iy1 - rect.y))
        used_any = True

    if not used_any:
        raise RuntimeError("; ".join(errors) if errors else "rect intersected no monitor")
    return canvas

_wgc_sessions: dict[int, object] = {}
_wgc_monitor_map: dict[int, int] | None = None


def _wgc_session(monitor_index: int):
    s = _wgc_sessions.get(monitor_index)
    if s is not None:
        return s
    import windows_capture  # type: ignore

    s = windows_capture.DxgiDuplicationSession(monitor_index=monitor_index)
    _wgc_sessions[monitor_index] = s
    return s


def _wgc_candidates_for_win(win_idx: int, monitor_count: int) -> list[int]:
    global _wgc_monitor_map
    if _wgc_monitor_map and win_idx in _wgc_monitor_map:
        preferred = _wgc_monitor_map[win_idx]
    else:
        preferred = win_idx + 1
    candidates = [preferred]
    candidates.extend(i for i in range(1, monitor_count + 1) if i != preferred)
    return candidates


def _hdr_tone_map_scrgb_to_srgb(arr):
    """scRGB linear float16 -> sRGB uint8.

    scRGB convention: 1.0 = 80 nits SDR white. HDR highlights have values
    above 1.0. Preserve the SDR range and clip out-of-range HDR highlights
    into SDR white so normal desktop content is not captured too dark.
    """
    import numpy as np

    rgb = arr[:, :, :3].astype(np.float32)
    # scRGB allows negative and >1.0 values. The PNG/clipboard path is SDR, so
    # keep the visible SDR range intact and clip HDR-only highlights.
    rgb = np.clip(rgb, 0.0, 1.0)
    # Linear -> sRGB gamma.
    a = 0.055
    encoded = np.where(
        rgb <= 0.0031308,
        rgb * 12.92,
        (1 + a) * np.power(np.clip(rgb, 1e-12, 1.0), 1.0 / 2.4) - a,
    )
    return np.clip(encoded * 255.0, 0, 255).astype(np.uint8)


def _apply_dxgi_display_correction(img: Image.Image) -> Image.Image:
    """Reduce DXGI fallback over-brightness on HDR / wide-gamut desktops.

    GDI/Qt captures already include Windows' desktop color management and skip
    this path. DXGI frames can be closer to the raw framebuffer, which users see
    as washed out once saved as a normal SDR PNG. Compress clipped highlights
    and then apply a mild gamma curve so white UI regions keep text contrast.
    """
    try:
        import numpy as np

        arr = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
        lum = (
            arr[:, :, 0] * 0.2126
            + arr[:, :, 1] * 0.7152
            + arr[:, :, 2] * 0.0722
        )
        p95 = float(np.percentile(lum, 95))
        p99 = float(np.percentile(lum, 99))

        # Washed-out DXGI captures usually have large regions pinned near
        # white. Map the top end down to an SDR-looking paper white before
        # gamma; this preserves relative color while avoiding blown highlights.
        if p95 > 0.82:
            target_white = 0.88
            scale = min(1.0, target_white / max(p99, 1e-6))
            arr *= scale
            gamma = 1.12
        else:
            gamma = 1.08

        arr = np.power(np.clip(arr, 0.0, 1.0), gamma)
        return Image.fromarray(np.clip(arr * 255.0, 0, 255).astype(np.uint8), "RGB")
    except Exception:
        return img.convert("RGB")


def _wgc_frame_to_pil(frame) -> Image.Image:
    """Convert a DxgiDuplicationFrame to a PIL RGB image, applying HDR
    tone-mapping when the frame is in float16 format."""
    import numpy as np

    arr = frame.to_numpy(copy=False)
    fmt = str(frame.color_format).lower()
    if arr.dtype == np.float16 or "float" in fmt or "16" in fmt:
        rgb = _hdr_tone_map_scrgb_to_srgb(arr)
        return _apply_dxgi_display_correction(Image.fromarray(rgb, "RGB"))
    # 8-bit BGRA / RGBA path.
    rgb_arr = arr[:, :, :3]
    if "bgr" in fmt:
        rgb_arr = rgb_arr[:, :, ::-1]
    return _apply_dxgi_display_correction(Image.fromarray(rgb_arr.copy(), "RGB"))


def _grab_wgc(rect: Rect) -> Image.Image:
    """Per-monitor capture via Windows Graphics Capture (HDR-aware).

    WGC's monitor enumeration matches the system's DISPLAY device order, which
    is the same order Win32 EnumDisplayMonitors returns — so win_idx maps 1:1.
    """
    global _wgc_monitor_map
    monitor_infos = _win32_monitor_infos()
    if not monitor_infos:
        raise RuntimeError("no Win32 monitors found")

    canvas = Image.new("RGB", (rect.w, rect.h), (0, 0, 0))
    used_any = False
    monitor_errors: list[str] = []
    for win_idx, monitor in enumerate(monitor_infos):
        mx, my, mw, mh = monitor.rect.x, monitor.rect.y, monitor.rect.w, monitor.rect.h
        ix1 = max(mx, rect.x)
        iy1 = max(my, rect.y)
        ix2 = min(mx + mw, rect.right)
        iy2 = min(my + mh, rect.bottom)
        if ix2 <= ix1 or iy2 <= iy1:
            continue
        img = None
        accepted_wgc_idx = None
        for wgc_idx in _wgc_candidates_for_win(win_idx, len(monitor_infos)):
            try:
                session = _wgc_session(wgc_idx)
                frame = session.acquire_frame(timeout_ms=300)
                if frame is None:
                    # First grab on a fresh session sometimes returns nothing.
                    time.sleep(0.05)
                    frame = session.acquire_frame(timeout_ms=300)
                if frame is None:
                    _log(f"WGC monitor {win_idx} (wgc {wgc_idx}): no frame")
                    continue
                candidate = _wgc_frame_to_pil(frame)
            except Exception as e:
                _log(f"WGC monitor {win_idx} (wgc {wgc_idx}) raised: {e}")
                monitor_errors.append(f"monitor {win_idx}/wgc {wgc_idx}: {e}")
                _wgc_sessions.pop(wgc_idx, None)
                continue
            if candidate.size != (mw, mh):
                msg = f"WGC monitor {win_idx} candidate {wgc_idx} size {candidate.size} != win32 ({mw}x{mh})"
                _log(msg)
                monitor_errors.append(msg)
                continue
            img = candidate
            accepted_wgc_idx = wgc_idx
            break
        if img is None:
            continue
        if _wgc_monitor_map is None:
            _wgc_monitor_map = {}
        _wgc_monitor_map[win_idx] = accepted_wgc_idx
        sx1 = ix1 - mx
        sy1 = iy1 - my
        sx2 = ix2 - mx
        sy2 = iy2 - my
        piece = img.crop((sx1, sy1, sx2, sy2))
        canvas.paste(piece, (ix1 - rect.x, iy1 - rect.y))
        used_any = True

    if not used_any:
        detail = "; ".join(monitor_errors) if monitor_errors else "rect intersected no monitor"
        raise RuntimeError(detail)
    return canvas


# --- bettercam backend ----------------------------------------------------

_bettercam_cameras: dict[int, object] = {}
_bettercam_monitor_map: dict[int, int] | None = None  # win32_idx -> bettercam_idx


def _build_bettercam_monitor_map() -> dict[int, int]:
    """Match Win32 monitor indices to bettercam output indices.

    EnumDisplayMonitors and bettercam's DXGI enumeration aren't guaranteed to
    be in the same order; with mixed-DPI multi-monitor setups they often
    aren't. We match the primary monitor (Win32: position (0,0); bettercam:
    Primary:True flag) and pair the rest by enumeration order.
    """
    import re

    import bettercam  # type: ignore

    win_infos = _win32_monitor_infos()
    if not win_infos:
        return {}

    info = bettercam.output_info().strip()
    bc_outputs = []
    for line in info.split("\n"):
        m = re.match(
            r"Device\[\d+\] Output\[(\d+)\]: Res:\((\d+), (\d+)\) Rot:\d+ Primary:(True|False)",
            line.strip(),
        )
        if m:
            idx, w, h, primary = m.groups()
            bc_outputs.append(
                {
                    "idx": int(idx),
                    "primary": primary == "True",
                    "size": (int(w), int(h)),
                }
            )
    if not bc_outputs:
        # Fallback: identity mapping.
        return {i: i for i in range(len(win_infos))}

    qt_logical_by_win: dict[int, tuple[int, int]] = {}
    try:
        from PySide6.QtGui import QGuiApplication

        qt_to_phys = qt_screen_to_monitor_rects()
        for qs, phys in qt_to_phys.items():
            for wi, info in enumerate(win_infos):
                if info.rect == phys:
                    g = qs.geometry()
                    qt_logical_by_win[wi] = (int(g.width()), int(g.height()))
                    break
    except Exception as e:
        _log(f"bettercam Qt logical mapping failed: {e}")

    mapping: dict[int, int] = {}
    unused_outputs = list(bc_outputs)
    for wi, size in qt_logical_by_win.items():
        match = next((o for o in unused_outputs if o["size"] == size), None)
        if match is not None:
            mapping[wi] = int(match["idx"])
            unused_outputs.remove(match)

    primary_win = next(
        (i for i, info in enumerate(win_infos) if info.primary),
        0,
    )
    primary_bc = next((o["idx"] for o in bc_outputs if o["primary"]), 0)
    if primary_win not in mapping:
        mapping[primary_win] = primary_bc

    remaining_win = [i for i in range(len(win_infos)) if i not in mapping]
    used_bc = set(mapping.values())
    remaining_bc = [o["idx"] for o in bc_outputs if o["idx"] not in used_bc]
    for wi, bc in zip(remaining_win, remaining_bc):
        mapping[wi] = bc
    _log(f"bettercam mapping (win_idx -> bc_idx): {mapping}")
    return mapping


def _bc_idx_for_win(win_idx: int) -> int:
    global _bettercam_monitor_map
    if _bettercam_monitor_map is None:
        try:
            _bettercam_monitor_map = _build_bettercam_monitor_map()
        except Exception as e:
            _log(f"bettercam mapping build failed: {e}")
            _bettercam_monitor_map = {}
    return _bettercam_monitor_map.get(win_idx, win_idx)


def _get_bettercam(output_idx: int):
    cam = _bettercam_cameras.get(output_idx)
    if cam is not None:
        return cam
    import bettercam  # type: ignore

    cam = bettercam.create(output_idx=output_idx, output_color="RGB")
    _bettercam_cameras[output_idx] = cam
    return cam


def _bettercam_full_frame(output_idx: int) -> Image.Image | None:
    cam = _get_bettercam(output_idx)
    arr = cam.grab()
    if arr is None:
        time.sleep(0.04)
        arr = cam.grab()
    if arr is None:
        return None
    return _apply_dxgi_display_correction(Image.fromarray(arr))


def _grab_bettercam(rect: Rect) -> Image.Image:
    """Capture each monitor that the rect intersects and composite."""
    monitor_rects = _win32_monitor_rects()
    if not monitor_rects:
        raise RuntimeError("no Win32 monitors found")

    canvas = Image.new("RGB", (rect.w, rect.h), (0, 0, 0))
    used_any = False
    monitor_errors: list[str] = []
    for win_idx, (mx, my, mw, mh) in enumerate(monitor_rects):
        ix1 = max(mx, rect.x)
        iy1 = max(my, rect.y)
        ix2 = min(mx + mw, rect.right)
        iy2 = min(my + mh, rect.bottom)
        if ix2 <= ix1 or iy2 <= iy1:
            continue
        bc_idx = _bc_idx_for_win(win_idx)
        try:
            full = _bettercam_full_frame(bc_idx)
        except Exception as e:
            _log(f"bettercam output {bc_idx} (win {win_idx}) failed: {e}")
            monitor_errors.append(f"monitor {win_idx}/bettercam {bc_idx}: {e}")
            _bettercam_cameras.pop(bc_idx, None)
            continue
        if full is None:
            _log(f"bettercam output {bc_idx} (win {win_idx}) returned no frame")
            continue
        if full.size != (mw, mh):
            _log(
                f"bettercam {bc_idx} size {full.size} != win32 {win_idx} ({mw}x{mh}); resizing"
            )
            full = full.resize((mw, mh), Image.BILINEAR)
        sx1 = ix1 - mx
        sy1 = iy1 - my
        sx2 = ix2 - mx
        sy2 = iy2 - my
        piece = full.crop((sx1, sy1, sx2, sy2))
        canvas.paste(piece, (ix1 - rect.x, iy1 - rect.y))
        used_any = True

    if not used_any:
        detail = "; ".join(monitor_errors) if monitor_errors else "rect intersected no monitor"
        raise RuntimeError(detail)
    return canvas


# --- mss / PIL / Qt fallbacks ---------------------------------------------

def _grab_mss(rect: Rect) -> Image.Image:
    import mss as _mss

    with _mss.mss() as sct:
        raw = sct.grab(rect.to_mss())
    return Image.frombytes("RGB", raw.size, raw.rgb)


def _grab_pil(rect: Rect) -> Image.Image:
    from PIL import ImageGrab

    bbox = (rect.x, rect.y, rect.right, rect.bottom)
    if sys.platform == "win32":
        try:
            return ImageGrab.grab(
                bbox=bbox, all_screens=True, include_layered_windows=True
            ).convert("RGB")
        except Exception:
            # Some driver/security-hook combinations fail when CAPTUREBLT /
            # layered windows are requested. Retry the simpler post-composited
            # path before falling through to DXGI.
            return ImageGrab.grab(bbox=bbox, all_screens=True).convert("RGB")
    return ImageGrab.grab(bbox=bbox).convert("RGB")


def _grab_qt(rect: Rect) -> Image.Image:
    from PySide6.QtGui import QGuiApplication

    screens = QGuiApplication.screens()
    if not screens:
        raise RuntimeError("Qt: no screens available")

    qt_to_phys = qt_screen_to_monitor_rects()
    canvas = Image.new("RGB", (rect.w, rect.h), (0, 0, 0))
    for s in screens:
        g = s.geometry()
        phys = qt_to_phys.get(s)
        if phys is not None:
            sx, sy, sw, sh = phys.x, phys.y, phys.w, phys.h
        else:
            dpr = s.devicePixelRatio() or 1.0
            sx = int(round(g.left() * dpr))
            sy = int(round(g.top() * dpr))
            sw = int(round(g.width() * dpr))
            sh = int(round(g.height() * dpr))
        ix1 = max(sx, rect.x)
        iy1 = max(sy, rect.y)
        ix2 = min(sx + sw, rect.right)
        iy2 = min(sy + sh, rect.bottom)
        if ix2 <= ix1 or iy2 <= iy1:
            continue
        pix = s.grabWindow(0, 0, 0, g.width(), g.height())
        qimg = pix.toImage()
        if qimg.width() != sw or qimg.height() != sh:
            qimg = qimg.scaled(sw, sh)
        from ..utils.image import qimage_to_pil

        full = qimage_to_pil(qimg).convert("RGB")
        piece = full.crop((ix1 - sx, iy1 - sy, ix2 - sx, iy2 - sy))
        canvas.paste(piece, (ix1 - rect.x, iy1 - rect.y))
    return canvas


# --- blank detection ------------------------------------------------------

def _looks_blank(img: Image.Image) -> bool:
    """Return True only for genuinely flat black/blank captures.

    Dark applications often have several matching sample points, so sample-only
    checks can reject valid captures. Use image-wide extrema on a thumbnail
    first, then only treat near-uniform very dark frames as blank.
    """
    w, h = img.size
    if w < 4 or h < 4:
        return False
    try:
        thumb = img.convert("RGB").resize((64, 64), Image.BILINEAR)
        extrema = thumb.getextrema()
        ranges = [hi - lo for lo, hi in extrema]
        means = []
        pixels = list(thumb.getdata())
        if pixels:
            n = len(pixels)
            means = [sum(p[i] for p in pixels) / n for i in range(3)]
        if max(ranges) > 12:
            return False
        if means and 12 <= max(means) <= 243:
            return False
    except Exception:
        pass
    points = [
        (w // 2, h // 2),
        (w // 4, h // 4),
        (3 * w // 4, h // 4),
        (w // 4, 3 * h // 4),
        (3 * w // 4, 3 * h // 4),
    ]
    sample = [img.getpixel(p)[:3] for p in points]
    first = sample[0]
    is_uniform = all(abs(a - b) < 4 for px in sample for a, b in zip(px, first))
    return is_uniform and (max(first) < 12 or min(first) > 243)


# --- public API -----------------------------------------------------------

if sys.platform == "win32":
    _BACKENDS = (
        # Modern Windows.Graphics.Capture path. This is the primary backend for
        # color fidelity and mixed-DPI monitor correctness.
        ("windows_capture", _grab_windows_capture),
        # GDI/Qt paths are closest to the already-composited image the user
        # sees after Windows color management. Try them before DXGI, which can
        # be too bright on HDR / wide-gamut displays.
        ("mss", _grab_mss),
        ("pil", _grab_pil),
        ("qt", _grab_qt),
        ("bettercam", _grab_bettercam),
        ("wgc", _grab_wgc),
    )
else:
    _BACKENDS = (
        ("mss", _grab_mss),
        ("pil", _grab_pil),
        ("qt", _grab_qt),
    )


def _image_stats(img: Image.Image) -> str:
    """Sample mean luminance to diagnose blank/HDR/oversaturated captures."""
    try:
        thumb = img.resize((32, 32), Image.BILINEAR)
        pixels = list(thumb.getdata())
        if not pixels:
            return "stats=empty"
        rs = [p[0] for p in pixels]
        gs = [p[1] for p in pixels]
        bs = [p[2] for p in pixels]
        n = len(pixels)
        rm, gm, bm = sum(rs) // n, sum(gs) // n, sum(bs) // n
        rmin, rmax = min(rs), max(rs)
        return f"mean=({rm},{gm},{bm}) r_range=[{rmin},{rmax}]"
    except Exception:
        return "stats=err"


def grab(rect: Rect) -> Image.Image:
    if rect.w <= 0 or rect.h <= 0:
        raise ValueError("invalid rect")

    errors: list[str] = []
    blank_result: Image.Image | None = None
    _log(f"--- grab requested rect={rect} ---")
    for name, fn in _BACKENDS:
        try:
            img = fn(rect)
        except Exception as e:
            errors.append(f"{name}: {type(e).__name__}: {e}")
            _log(f"backend {name} raised: {e}")
            continue
        stats = _image_stats(img)
        if _looks_blank(img):
            errors.append(f"{name}: returned blank image ({stats})")
            _log(f"backend {name} returned blank ({stats}) — trying next")
            if blank_result is None:
                blank_result = img
            continue
        _log(f"capture OK via {name} ({img.width}x{img.height}) {stats}")
        return img

    if blank_result is not None:
        _log("ALL backends returned blank. Errors:\n  " + "\n  ".join(errors))
        raise RuntimeError("화면 캡처가 검은 화면으로만 반환되었습니다.\n  " + "\n  ".join(errors))
    raise RuntimeError("화면 캡처 실패. 시도한 방법:\n  " + "\n  ".join(errors))


def grab_full() -> Image.Image:
    return grab(virtual_screen_rect())
