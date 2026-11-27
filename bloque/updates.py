from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from . import __version__, net

REPO = "nadiusk80-oss/Blockys-Launcher"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{REPO}/releases/latest"
INSTALLER_PREFIX = "blockys-setup"
SUMS_NAME = "sha256sums.txt"


class UpdateError(Exception):
    pass


def _parse(version: str) -> tuple[int, ...] | None:
    match = re.search(r"(\d+(?:\.\d+)+)", str(version or ""))
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def is_newer(remote: str, local: str = __version__) -> bool:
    remote_parts = _parse(remote)
    local_parts = _parse(local)
    if remote_parts is None or local_parts is None:
        return False
    size = max(len(remote_parts), len(local_parts))
    remote_parts += (0,) * (size - len(remote_parts))
    local_parts += (0,) * (size - len(local_parts))
    return remote_parts > local_parts


def _release_version(data: dict) -> str:
    candidates = [data.get("tag_name"), data.get("name")]
    for asset in data.get("assets") or []:
        if isinstance(asset, dict):
            candidates.append(asset.get("name"))
    for value in candidates:
        match = re.search(r"(\d+(?:\.\d+)+)", str(value or ""))
        if match:
            return match.group(1)
    return ""


def _assets(data: dict) -> list[dict]:
    assets = []
    for asset in data.get("assets") or []:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "")
        url = str(asset.get("browser_download_url") or "")
        if not name or not url:
            continue
        try:
            size = int(asset.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        assets.append({"name": name, "url": url, "size": size})
    return assets


def _pick_installer(assets: list[dict]) -> dict | None:
    for asset in assets:
        name = asset["name"].lower()
        if name.startswith(INSTALLER_PREFIX) and name.endswith(".exe"):
            return dict(asset)
    return None


def _parse_sums(text: str, installer_name: str) -> str:
    for line in str(text or "").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == installer_name:
            digest = parts[0].strip().lower()
            if re.fullmatch(r"[0-9a-f]{64}", digest):
                return digest
    return ""


def _remote_sha256(assets: list[dict], installer_name: str) -> str:
    for asset in assets:
        if asset["name"].lower() == SUMS_NAME:
            try:
                _, body = net.request(asset["url"], timeout=20)
            except (net.HttpError, net.ConnectionError_):
                return ""
            return _parse_sums(body.decode("utf-8", "replace"), installer_name)
    return ""


def check_latest(timeout: int = 15) -> dict:
    try:
        data = net.http_json(API_LATEST, timeout=timeout,
                             headers={"Accept": "application/vnd.github+json"})
    except net.HttpError as exc:
        if exc.status == 404:
            raise UpdateError(
                "No hay versiones publicadas todavía en GitHub") from exc
        raise UpdateError(f"GitHub respondió {exc.status}") from exc
    except net.ConnectionError_ as exc:
        raise UpdateError(f"Sin conexión con GitHub: {exc}") from exc
    if not isinstance(data, dict) or not data.get("tag_name"):
        raise UpdateError("GitHub no devolvió una versión válida")
    version = _release_version(data)
    if not version:
        raise UpdateError("La última publicación no indica un número de versión")
    assets = _assets(data)
    installer = _pick_installer(assets)
    if installer is not None:
        installer["sha256"] = _remote_sha256(assets, installer["name"])
    return {
        "tag": version,
        "url": str(data.get("html_url") or RELEASES_URL),
        "name": str(data.get("name") or version),
        "notes": str(data.get("body") or ""),
        "newer": is_newer(version),
        "current": __version__,
        "installer": installer,
    }


def _installed_exe() -> Path | None:
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable)
        if exe.is_file():
            return exe
    return None


def is_self_update_supported() -> bool:
    return _installed_exe() is not None


def download_update(info: dict, on_progress=None,
                    cancel_event=None) -> Path:
    installer = info.get("installer") or {}
    url = str(installer.get("url") or "")
    name = Path(str(installer.get("name") or "")).name
    if not url or not name.lower().endswith(".exe"):
        raise UpdateError(
            "La última versión no incluye un instalador para Windows")
    folder = Path(tempfile.gettempdir()) / "Blockys-updates"
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / name
    try:
        net.download_one(url, dest,
                         sha256=installer.get("sha256") or None,
                         size=installer.get("size") or None,
                         on_progress=on_progress, cancel_event=cancel_event)
    except net.Cancelled:
        raise
    except net.DownloadError as exc:
        raise UpdateError(f"No se pudo descargar el instalador: {exc}") from exc
    return dest


def _helper_script(setup: Path, target: Path, pid: int) -> str:
    return (
        "@echo off\r\n"
        "powershell -NoProfile -Command \"while (Get-Process -Id "
        f"{int(pid)} -ErrorAction SilentlyContinue) "
        "{ Start-Sleep -Milliseconds 400 }\"\r\n"
        f"start \"\" /wait \"{setup}\" /SILENT /NORESTART /SP- "
        "/SUPPRESSMSGBOXES /CLOSEAPPLICATIONS\r\n"
        f"if exist \"{target}\" start \"\" \"{target}\"\r\n"
        "exit /b 0\r\n"
    )


def apply_update(setup: Path) -> Path:
    target = _installed_exe()
    if target is None:
        raise UpdateError(
            "La actualización automática solo funciona en la versión instalada")
    setup = Path(setup)
    if not setup.is_file():
        raise UpdateError("No se encontró el instalador descargado")
    script = Path(tempfile.gettempdir()) / f"blockys-update-{os.getpid()}.cmd"
    script.write_text(_helper_script(setup, target, os.getpid()),
                      encoding="utf-8")
    flags = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
             | getattr(subprocess, "DETACHED_PROCESS", 0))
    subprocess.Popen(["cmd", "/c", str(script)], close_fds=True,
                     creationflags=flags)
    return target
