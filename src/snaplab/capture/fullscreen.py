"""Full-screen captures."""
from __future__ import annotations

from PIL import Image

from . import screen


def capture_all() -> Image.Image:
    """Capture the union of all monitors."""
    return screen.grab_full()


def capture_primary() -> Image.Image:
    mons = screen.monitors()
    if not mons:
        return screen.grab_full()
    return screen.grab(mons[0])
