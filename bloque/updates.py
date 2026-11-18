from __future__ import annotations

import re

from . import __version__, net

REPO = "nadiusk80-oss/Blockys-Launcher"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{REPO}/releases/latest"


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
    return {
        "tag": version,
        "url": str(data.get("html_url") or RELEASES_URL),
        "name": str(data.get("name") or version),
        "notes": str(data.get("body") or ""),
        "newer": is_newer(version),
        "current": __version__,
    }
