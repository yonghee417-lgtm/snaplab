"""Cross-platform auto-start on login.

Windows: writes HKCU\\...\\Run registry value.
macOS: writes a LaunchAgent plist in ~/Library/LaunchAgents.
Linux: writes a .desktop file in ~/.config/autostart.
"""
from __future__ import annotations

import sys
from pathlib import Path

from . import APP_NAME


def _exe_command() -> str:
    """Command line that re-launches this app."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    py = sys.executable
    return f'"{py}" -m {APP_NAME}'


def is_enabled() -> bool:
    if sys.platform == "win32":
        return _win_is_enabled()
    if sys.platform == "darwin":
        return _mac_plist_path().exists()
    return _linux_desktop_path().exists()


def set_enabled(enabled: bool) -> bool:
    try:
        if sys.platform == "win32":
            return _win_set(enabled)
        if sys.platform == "darwin":
            return _mac_set(enabled)
        return _linux_set(enabled)
    except Exception:
        return False


# --- Windows ---------------------------------------------------------------

def _win_key():
    import winreg

    return winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Run",
        0,
        winreg.KEY_READ | winreg.KEY_WRITE,
    )


def _win_is_enabled() -> bool:
    try:
        import winreg

        with _win_key() as k:
            winreg.QueryValueEx(k, APP_NAME)
            return True
    except (FileNotFoundError, OSError):
        return False


def _win_set(enabled: bool) -> bool:
    import winreg

    with _win_key() as k:
        if enabled:
            winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, _exe_command())
        else:
            try:
                winreg.DeleteValue(k, APP_NAME)
            except FileNotFoundError:
                pass
    return True


# --- macOS -----------------------------------------------------------------

def _mac_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"com.snaplab.{APP_NAME}.plist"


def _mac_set(enabled: bool) -> bool:
    p = _mac_plist_path()
    if not enabled:
        if p.exists():
            p.unlink()
        return True
    p.parent.mkdir(parents=True, exist_ok=True)
    if getattr(sys, "frozen", False):
        program_args = f"<string>{sys.executable}</string>"
    else:
        program_args = (
            f"<string>{sys.executable}</string>\n"
            f"            <string>-m</string>\n"
            f"            <string>{APP_NAME}</string>"
        )
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.snaplab.{APP_NAME}</string>
    <key>ProgramArguments</key>
    <array>
            {program_args}
    </array>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
"""
    p.write_text(plist, encoding="utf-8")
    return True


# --- Linux -----------------------------------------------------------------

def _linux_desktop_path() -> Path:
    return Path.home() / ".config" / "autostart" / f"{APP_NAME}.desktop"


def _linux_set(enabled: bool) -> bool:
    p = _linux_desktop_path()
    if not enabled:
        if p.exists():
            p.unlink()
        return True
    p.parent.mkdir(parents=True, exist_ok=True)
    body = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_NAME}\n"
        f"Exec={_exe_command()}\n"
        "X-GNOME-Autostart-enabled=true\n"
    )
    p.write_text(body, encoding="utf-8")
    return True
