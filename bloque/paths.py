from __future__ import annotations

import os
import sys
from pathlib import Path

from .util import load_json, save_json

APP_NAME = "Blockys"
STORAGE_NAME = "BloqueLauncher"  # mantiene cuentas e instancias de versiones previas


def _base_dir() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


APP_DIR = _base_dir() / STORAGE_NAME
DATA_DIR = APP_DIR / "data"
VERSIONS_DIR = DATA_DIR / "versions"
LIBRARIES_DIR = DATA_DIR / "libraries"
ASSETS_DIR = DATA_DIR / "assets"
RUNTIME_DIR = DATA_DIR / "runtime"
CACHE_DIR = APP_DIR / "cache"
SKINS_DIR = APP_DIR / "skins"
LOGS_DIR = APP_DIR / "logs"
INSTANCES_DIR = APP_DIR / "instances"
AUTHLIB_DIR = APP_DIR / "authlib"

SETTINGS_FILE = APP_DIR / "settings.json"
PROFILES_FILE = APP_DIR / "profiles.json"
MANIFEST_FILE = APP_DIR / "manifest.json"
INSTANCES_FILE = APP_DIR / "instances.json"


def default_game_dir() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home()) / ".minecraft"
    return Path.home() / ".minecraft"


DEFAULT_MEMORY_MB = 2048 if sys.maxsize > 2**32 else 1024

DEFAULT_SETTINGS = {
    "memory_mb": DEFAULT_MEMORY_MB,
    "game_dir": str(default_game_dir()),
    "java_mode": "temurin",
    "java_path": "",
    "client_id": "",
    "resolution_width": 1280,
    "resolution_height": 720,
    "custom_resolution": False,
    "selected_version": "",
    "selected_profile": "",
    "version_type": "release",
    "copy_skin_mod": True,
    "aikar_flags": True,
    "proxy_type": "none",
    "proxy_host": "",
    "proxy_port": "8080",
    "check_updates": True,
    "instance_sort": "name",
    "collapsed_groups": [],
    "onboarding_done": False,
}


def ensure_dirs() -> None:
    for folder in (APP_DIR, DATA_DIR, VERSIONS_DIR, LIBRARIES_DIR, ASSETS_DIR,
                   RUNTIME_DIR, CACHE_DIR, SKINS_DIR, LOGS_DIR, INSTANCES_DIR,
                   AUTHLIB_DIR):
        folder.mkdir(parents=True, exist_ok=True)


def load_settings() -> dict:
    data = load_json(SETTINGS_FILE, {})
    settings = dict(DEFAULT_SETTINGS)
    if isinstance(data, dict):
        settings.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS})
    try:
        settings["memory_mb"] = max(512, min(32768, int(settings["memory_mb"])))
    except (TypeError, ValueError):
        settings["memory_mb"] = DEFAULT_SETTINGS["memory_mb"]
    return settings


def save_settings(settings: dict) -> None:
    ensure_dirs()
    save_json(SETTINGS_FILE, settings)


def load_store() -> dict:
    data = load_json(PROFILES_FILE, {})
    if not isinstance(data, dict) or not isinstance(data.get("profiles"), list):
        return {"profiles": [], "selected": ""}
    return data


def save_store(store: dict) -> None:
    ensure_dirs()
    save_json(PROFILES_FILE, store)
