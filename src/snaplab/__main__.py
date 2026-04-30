"""Module entrypoint: `python -m snaplab` (or installed `snaplab` script)."""
from __future__ import annotations

import os
import sys


def _configure_qt_env() -> None:
    """Defensive Qt env vars set before PySide6 imports.

    On some Windows configurations Qt's default GDI raster backend hits
    "BitBlt failed (module not found)" because of broken display-driver hooks
    (NVIDIA Overlay, AMD ReLive, screen recorders, EDR security tools). These
    flags bias Qt toward safer paths.
    """
    os.environ.setdefault("QT_OPENGL", "software")
    os.environ.setdefault("QT_QUICK_BACKEND", "software")
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
    # Avoid blaming us for benign warnings on stderr.
    os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.window.warning=false")

    if sys.platform == "win32":
        try:
            import ctypes

            awareness = ctypes.c_void_p(-4)  # PER_MONITOR_AWARE_V2
            ctypes.windll.user32.SetProcessDpiAwarenessContext(awareness)
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


_configure_qt_env()


from .app import run  # noqa: E402  (after env setup)


def main() -> int:
    return run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
