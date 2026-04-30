"""Bundle snaplab into a standalone executable using PyInstaller.

Usage:
    python build.py            # build for current platform
    python build.py --clean    # remove build/dist first
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
DIST = ROOT / "dist"
BUILD = ROOT / "build"


def _icon_arg() -> list[str]:
    if sys.platform == "win32":
        ico = ASSETS / "logo.ico"
        if ico.exists():
            return [f"--icon={ico}"]
    elif sys.platform == "darwin":
        icns = ASSETS / "logo.icns"
        if icns.exists():
            return [f"--icon={icns}"]
    return []


def main() -> int:
    if "--clean" in sys.argv:
        for p in (DIST, BUILD):
            if p.exists():
                shutil.rmtree(p)
        for spec in ROOT.glob("*.spec"):
            spec.unlink()

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller가 필요합니다. `pip install pyinstaller` 실행 후 다시 시도하세요.")
        return 1

    # Hidden imports: dynamically-imported modules PyInstaller's static analysis
    # misses (capture backends, Qt platform plugins, etc.).
    hidden = [
        "bettercam",
        "comtypes",
        "comtypes.client",
        "cv2",
        "pynput",
        "pynput.keyboard._win32",
        "pynput.mouse._win32",
        "PIL.ImageGrab",
        "mss",
        "mss.windows",
        "websocket",
        "win32api",
        "win32gui",
        "win32con",
    ]

    cmd: list[str] = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--name=snaplab",
        "--noconfirm",
        "--windowed",       # no console on Windows/macOS
        "--onedir",         # one-folder build — fast startup, easier antivirus
        f"--add-data={ASSETS}{_sep()}assets",
        "--paths=src",
        "--collect-submodules=PySide6",
        *[f"--hidden-import={m}" for m in hidden],
        *_icon_arg(),
        "src/snaplab/__main__.py",
    ]
    print("Running:", " ".join(cmd))
    return subprocess.run(cmd, cwd=ROOT).returncode


def _sep() -> str:
    return ";" if sys.platform == "win32" else ":"


if __name__ == "__main__":
    raise SystemExit(main())
