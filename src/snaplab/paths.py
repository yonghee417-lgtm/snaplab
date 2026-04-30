"""Centralized filesystem paths used across the app."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from . import APP_NAME


def project_root() -> Path:
    """Return repo root when running from source; resolves to bundle dir when frozen."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parents[2]


def assets_dir() -> Path:
    return project_root() / "assets"


def user_data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    p = base / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def settings_path() -> Path:
    return user_data_dir() / "settings.json"


def history_dir() -> Path:
    p = user_data_dir() / "history"
    p.mkdir(parents=True, exist_ok=True)
    return p


def default_save_dir() -> Path:
    p = Path.home() / "Pictures" / "snaplab"
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError:
        p = user_data_dir() / "captures"
        p.mkdir(parents=True, exist_ok=True)
    return p


def find_logo() -> Path | None:
    a = assets_dir()
    for name in ("logo.png", "logo@2x.png", "logo.ico"):
        f = a / name
        if f.exists():
            return f
    return None
