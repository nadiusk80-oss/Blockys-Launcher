from __future__ import annotations

import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from urllib.parse import quote

from . import java, net, paths
from .util import load_json, save_json
from .versions import required_java

FABRIC_META = "https://meta.fabricmc.net/v2"
QUILT_META = "https://meta.quiltmc.org/v3"
FORGE_PROMOS = "https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json"
FORGE_MAVEN = "https://maven.minecraftforge.net"
NEOFORGE_MAVEN = "https://maven.neoforged.net/releases"


class LoaderError(Exception):
    pass


def _version_key(value: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", value or "")
    return tuple(int(part) for part in parts[:6]) or (0,)


def _http_text(url: str) -> str:
    _, body = net.request(url)
    return body.decode("utf-8", "replace")


def _profile_id(loader: str, loader_version: str, game: str) -> str:
    return f"{loader}-loader-{loader_version}-{game}"


def _save_profile(profile: dict, loader: str, loader_version: str,
                  game: str) -> str:
    version_id = profile.get("id") or _profile_id(loader, loader_version, game)
    profile["id"] = version_id
    profile.setdefault("inheritsFrom", game)
    folder = paths.VERSIONS_DIR / version_id
    folder.mkdir(parents=True, exist_ok=True)
    save_json(folder / f"{version_id}.json", profile)
    return version_id


def _fabric(game: str, loader_version: str, on_status) -> tuple[str, str]:
    if on_status:
        on_status("Consultando Fabric...")
    versions = net.http_json(f"{FABRIC_META}/versions/loader/{quote(game)}")
    if not versions:
        raise LoaderError(f"Fabric no tiene versiones para Minecraft {game}")
    if not loader_version:
        stable = [item for item in versions
                  if (item.get("loader") or {}).get("stable")]
        loader_version = ((stable or versions)[0].get("loader") or {}).get("version", "")
    if not loader_version:
        raise LoaderError("No se pudo elegir una version de Fabric")
    profile = net.http_json(
        f"{FABRIC_META}/versions/loader/{quote(game)}/{quote(loader_version)}/profile/json")
    return _save_profile(profile, "fabric", loader_version, game), loader_version


def _quilt(game: str, loader_version: str, on_status) -> tuple[str, str]:
    if on_status:
        on_status("Consultando Quilt...")
    versions = net.http_json(f"{QUILT_META}/versions/loader/{quote(game)}")
    if not versions:
        raise LoaderError(f"Quilt no tiene versiones para Minecraft {game}")
    if not loader_version:
        stable = [item for item in versions
                  if "beta" not in (item.get("loader") or {}).get("version", "").lower()
                  and "rc" not in (item.get("loader") or {}).get("version", "").lower()
                  and "alpha" not in (item.get("loader") or {}).get("version", "").lower()]
        first = (stable or versions)[0]
        loader_version = (first.get("loader") or {}).get("version", "")
    if not loader_version:
        raise LoaderError("No se pudo elegir una version de Quilt")
    profile = net.http_json(
        f"{QUILT_META}/versions/loader/{quote(game)}/{quote(loader_version)}/profile/json")
    return _save_profile(profile, "quilt", loader_version, game), loader_version


def _forge_version(game: str, loader_version: str, on_status) -> str:
    if loader_version:
        return loader_version
    try:
        promotions = net.http_json(FORGE_PROMOS).get("promos") or {}
        for suffix in ("recommended", "latest"):
            value = promotions.get(f"{game}-{suffix}")
            if value:
                return str(value)
    except Exception:
        pass
    if on_status:
        on_status("Consultando versiones de Forge...")
    text = _http_text(f"{FORGE_MAVEN}/net/minecraftforge/forge/maven-metadata.xml")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise LoaderError("No se pudo leer la lista de versiones de Forge") from exc
    candidates = []
    for node in root.findall(".//version"):
        value = (node.text or "").strip()
        prefix = f"{game}-"
        if value.startswith(prefix) and len(value) > len(prefix):
            candidates.append((_version_key(value[len(prefix):]), value[len(prefix):]))
    if not candidates:
        raise LoaderError(f"Forge no tiene una version para Minecraft {game}")
    return max(candidates)[1]


def _neoforge_version(game: str, loader_version: str, on_status) -> str:
    if loader_version:
        return loader_version
    if on_status:
        on_status("Consultando versiones de NeoForge...")
    if game == "1.20.1":
        raise LoaderError("NeoForge para 1.20.1 es experimental; elegi Forge 47.x")
    parts = game.split(".")
    if len(parts) < 2:
        raise LoaderError(f"No se pudo interpretar la version {game} para NeoForge")
    # NeoForge usa <minor>.<patch>.* para 1.x (1.21 -> 21.0.*, 1.21.1 -> 21.1.*)
    if game.startswith("1."):
        patch = parts[2] if len(parts) > 2 else "0"
        prefix = f"{parts[1]}.{patch}."
    else:
        prefix = f"{parts[0]}."
    text = _http_text(f"{NEOFORGE_MAVEN}/net/neoforged/neoforge/maven-metadata.xml")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise LoaderError("No se pudo leer la lista de versiones de NeoForge") from exc
    candidates = []
    for node in root.findall(".//version"):
        value = (node.text or "").strip()
        if not value.startswith(prefix):
            continue
        lower = value.lower()
        if any(tag in lower for tag in ("alpha", "beta", "snapshot")):
            continue
        candidates.append((_version_key(value), value))
    if not candidates:
        raise LoaderError(f"NeoForge no tiene una version estable para Minecraft {game}")
    return max(candidates)[1]


def _creation_flags() -> int:
    if sys.platform == "win32":
        return subprocess.CREATE_NO_WINDOW
    return 0


def _run_installer(installer: Path, java_exe: Path, label: str,
                   cancel_event=None) -> None:
    paths.ensure_dirs()
    profile_file = paths.DATA_DIR / "launcher_profiles.json"
    if not profile_file.exists():
        save_json(profile_file, {"profiles": {}, "settings": {}, "version": 3})
    log_path = paths.LOGS_DIR / f"installer-{label}-{time.strftime('%Y%m%d-%H%M%S')}.log"
    command = [str(java_exe), "-jar", str(installer), "--installClient",
               str(paths.DATA_DIR)]
    log = open(log_path, "wb")
    try:
        process = subprocess.Popen(
            command, cwd=str(paths.DATA_DIR), stdout=log,
            stderr=subprocess.STDOUT, creationflags=_creation_flags())
        deadline = time.time() + 1800
        while process.poll() is None:
            if cancel_event is not None and cancel_event.is_set():
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                raise net.Cancelled()
            if time.time() > deadline:
                process.kill()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
                raise LoaderError("El instalador tardo demasiado (30 minutos)")
            time.sleep(0.4)
        if process.returncode != 0:
            tail = ""
            try:
                log.flush()
                text = log_path.read_text(encoding="utf-8", errors="replace")
                tail = " ".join(line.strip() for line in text.splitlines()[-4:])
            except OSError:
                pass
            raise LoaderError(
                f"El instalador de {label} fallo (codigo {process.returncode})"
                + (f": {tail[:300]}" if tail else ""))
    finally:
        log.close()


def _find_installed(game: str, loader: str, loader_version: str) -> str | None:
    best: tuple[float, str] | None = None
    try:
        candidates = list(paths.VERSIONS_DIR.glob("*/*.json"))
    except OSError:
        return None
    for path in candidates:
        if path.parent.name != path.stem:
            continue
        data = load_json(path, {})
        if data.get("inheritsFrom") != game:
            continue
        version_id = data.get("id") or path.stem
        lower = version_id.lower()
        if loader == "neoforge":
            if "neoforge" not in lower:
                continue
        elif "forge" not in lower or "neoforge" in lower:
            continue
        if loader_version and loader_version.lower() not in lower:
            continue
        try:
            stamp = path.stat().st_mtime
        except OSError:
            stamp = 0
        if best is None or stamp > best[0]:
            best = (stamp, version_id)
    return best[1] if best else None


def _valid_installer(path: Path) -> bool:
    try:
        return path.stat().st_size > 100_000 and zipfile.is_zipfile(path)
    except OSError:
        return False


def _download_installer(url: str, name: str, on_status, cancel_event=None) -> Path:
    dest = paths.CACHE_DIR / name
    if _valid_installer(dest):
        return dest
    try:
        dest.unlink()
    except OSError:
        pass
    if on_status:
        on_status(f"Descargando {name}...")
    net.download_one(url, dest, cancel_event=cancel_event)
    if not _valid_installer(dest):
        try:
            dest.unlink()
        except OSError:
            pass
        raise LoaderError(f"El instalador de {name} no es un JAR valido")
    return dest


def _forge(game: str, loader_version: str, settings: dict, base_data: dict,
           on_status, on_progress, cancel_event) -> tuple[str, str]:
    loader_version = _forge_version(game, loader_version, on_status)
    full = f"{game}-{loader_version}"
    url = f"{FORGE_MAVEN}/net/minecraftforge/forge/{full}/forge-{full}-installer.jar"
    installer = _download_installer(url, f"forge-{full}-installer.jar", on_status,
                                    cancel_event)
    major = required_java(base_data)
    if on_status:
        on_status(f"Preparando Java {major} para el instalador de Forge...")
    java_exe = java.resolve_java(settings, major, on_status=on_status,
                                 cancel_event=cancel_event)
    if on_progress:
        on_progress(0.45, "Ejecutando instalador de Forge")
    if on_status:
        on_status("Instalando Forge (puede tardar varios minutos)...")
    _run_installer(installer, java_exe, f"forge-{full}", cancel_event)
    expected = f"{game}-forge-{loader_version}"
    installed = _find_installed(game, "forge", loader_version)
    version_id = expected if (paths.VERSIONS_DIR / expected / f"{expected}.json").is_file() \
        else installed
    if not version_id:
        raise LoaderError("Forge se instalo pero no se encontro su perfil de version")
    return version_id, loader_version


def _neoforge(game: str, loader_version: str, settings: dict, base_data: dict,
              on_status, on_progress, cancel_event) -> tuple[str, str]:
    loader_version = _neoforge_version(game, loader_version, on_status)
    url = (f"{NEOFORGE_MAVEN}/net/neoforged/neoforge/{loader_version}/"
           f"neoforge-{loader_version}-installer.jar")
    installer = _download_installer(url, f"neoforge-{loader_version}-installer.jar",
                                    on_status, cancel_event)
    major = required_java(base_data)
    if on_status:
        on_status(f"Preparando Java {major} para el instalador de NeoForge...")
    java_exe = java.resolve_java(settings, major, on_status=on_status,
                                 cancel_event=cancel_event)
    if on_progress:
        on_progress(0.45, "Ejecutando instalador de NeoForge")
    if on_status:
        on_status("Instalando NeoForge (puede tardar varios minutos)...")
    _run_installer(installer, java_exe, f"neoforge-{loader_version}", cancel_event)
    expected = f"neoforge-{loader_version}"
    installed = _find_installed(game, "neoforge", loader_version)
    version_id = expected if (paths.VERSIONS_DIR / expected / f"{expected}.json").is_file() \
        else installed
    if not version_id:
        raise LoaderError("NeoForge se instalo pero no se encontro su perfil de version")
    return version_id, loader_version


def ensure(loader: str, game: str, settings: dict, base_data: dict,
           loader_version: str = "", on_status=None, on_progress=None,
           cancel_event=None) -> dict:
    if not game:
        raise LoaderError("La instancia no tiene una version de Minecraft")
    paths.ensure_dirs()
    loader = (loader or "vanilla").lower()
    if loader in ("vanilla", "", "none"):
        return {"version_id": game, "loader_version": ""}
    if on_progress:
        on_progress(0.05, f"Preparando {loader.title()}")
    if loader == "fabric":
        version_id, resolved = _fabric(game, loader_version, on_status)
    elif loader == "quilt":
        version_id, resolved = _quilt(game, loader_version, on_status)
    elif loader == "forge":
        version_id, resolved = _forge(game, loader_version, settings, base_data,
                                      on_status, on_progress, cancel_event)
    elif loader == "neoforge":
        version_id, resolved = _neoforge(game, loader_version, settings, base_data,
                                         on_status, on_progress, cancel_event)
    else:
        raise LoaderError(f"Cargador desconocido: {loader}")
    if cancel_event is not None and cancel_event.is_set():
        raise net.Cancelled()
    return {"version_id": version_id, "loader_version": resolved}
