from __future__ import annotations

import platform
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

from . import net, paths
from .util import safe_extract

ADOPTIUM_API = ("https://api.adoptium.net/v3/assets/latest/{major}/hotspot"
                "?architecture={arch}&image_type=jre&os={os_name}&vendor=eclipse")

LINUX = sys.platform.startswith("linux")
MAC = sys.platform == "darwin"
WINDOWS = sys.platform == "win32"
IS_64 = sys.maxsize > 2**32


def _java_arch() -> str:
    machine = platform.machine().lower()
    if not IS_64:
        return "x86"
    if machine in ("arm64", "aarch64"):
        return "aarch64"
    return "x64"


JAVA_ARCH = _java_arch()

JAVA_MAJORS = (8, 11, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27)
FALLBACK_MAJOR = {
    16: 17, 15: 17, 14: 17, 13: 17, 12: 17, 10: 8, 9: 8, 7: 8, 6: 8,
}


def _creation_flags() -> int:
    return subprocess.CREATE_NO_WINDOW if WINDOWS else 0


def _java_name() -> str:
    return "java.exe" if WINDOWS else "java"


def find_java_in(home: Path) -> Path | None:
    name = _java_name()
    candidates = [home / "bin" / name]
    if MAC:
        candidates.append(home / "Contents" / "Home" / "bin" / name)
    candidates.extend(home.glob(f"*/bin/{name}"))
    candidates.extend(home.glob(f"*/*/bin/{name}"))
    candidates.extend(home.glob(f"*/*/*/bin/{name}"))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def java_version(java_exe: Path) -> str | None:
    try:
        result = subprocess.run(
            [str(java_exe), "-version"],
            capture_output=True, text=True, timeout=25,
            creationflags=_creation_flags(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = (result.stderr or "") + (result.stdout or "")
    match = re.search(r'version "([^"]+)"', text)
    if match:
        return match.group(1)
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return first or None


def _adoptium_query(major: int) -> dict:
    if WINDOWS:
        os_name = "windows"
    elif MAC:
        os_name = "mac"
    else:
        os_name = "linux"
    return net.http_json(ADOPTIUM_API.format(
        major=major, arch=JAVA_ARCH, os_name=os_name))


def _runtime_home(major: int) -> Path:
    suffix = "" if JAVA_ARCH == "x64" else f"-{JAVA_ARCH}"
    return paths.RUNTIME_DIR / f"temurin-{major}{suffix}"


def _missing_java(major: int) -> RuntimeError:
    if not IS_64:
        return RuntimeError(
            f"Temurin no publica Java {major} para Windows de 32 bits. "
            "En 32 bits solo hay Java 8, 11 y 17; esa version de Minecraft "
            "necesita una version mas nueva.")
    return RuntimeError(
        f"Adoptium no tiene un JRE Temurin {major} para este sistema")


def installed_runtime(major: int) -> tuple[Path, str] | None:
    home = _runtime_home(major)
    java_exe = find_java_in(home)
    if not java_exe:
        return None
    version = java_version(java_exe)
    return (java_exe, version) if version else None


def ensure_temurin(major: int, on_progress=None, on_status=None,
                   cancel_event=None) -> Path:
    paths.ensure_dirs()
    target = major
    releases = []
    for _ in range(3):
        installed = installed_runtime(target)
        if installed:
            if on_status:
                on_status(f"Temurin {target} ya esta instalado ({installed[1]})")
            if on_progress:
                on_progress(1.0, "Java Temurin listo")
            return installed[0]
        if on_status:
            on_status(f"Buscando Temurin {target} en Adoptium...")
        try:
            releases = _adoptium_query(target)
        except Exception:
            releases = []
        if releases:
            break
        fallback = FALLBACK_MAJOR.get(target)
        if fallback is None:
            raise _missing_java(target)
        if on_status:
            on_status(f"Temurin {target} no disponible, usando {fallback}...")
        target = fallback

    if not releases:
        raise _missing_java(target)

    home = _runtime_home(target)
    package = None
    for release in releases:
        binary = release.get("binary") or {}
        candidate = binary.get("package") or {}
        if candidate.get("link"):
            package = candidate
            break
    if not package:
        raise RuntimeError("Adoptium no devolvio un paquete descargable")

    url = package["link"]
    name = package.get("name") or url.rsplit("/", 1)[-1]
    size = package.get("size")
    sha256 = package.get("checksum")
    archive = paths.CACHE_DIR / name

    if on_status:
        on_status(f"Descargando Temurin {target}...")
    net.download_one(url, archive, sha256=sha256, size=size,
                     on_progress=on_progress, cancel_event=cancel_event)

    if on_status:
        on_status(f"Extrayendo Temurin {target}...")
    tmp = paths.RUNTIME_DIR / f"{home.name}.tmp"
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        if name.lower().endswith(".zip"):
            safe_extract(archive, tmp)
        else:
            with tarfile.open(archive) as tf:
                try:
                    tf.extractall(tmp, filter="data")
                except TypeError:
                    tf.extractall(tmp)
        java_exe = find_java_in(tmp)
        if not java_exe:
            raise RuntimeError("El paquete de Temurin no contiene bin/java")
        java_home = java_exe.parent.parent
        if home.exists():
            shutil.rmtree(home, ignore_errors=True)
        shutil.move(str(java_home), str(home))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    final = find_java_in(home)
    if not final:
        raise RuntimeError("No se encontro Java dentro de Temurin")
    version = java_version(final)
    if not version:
        raise RuntimeError("Java se descargo pero no pudo ejecutarse (posible bloqueo del sistema)")
    try:
        archive.unlink()
    except OSError:
        pass
    if on_progress:
        on_progress(1.0, "Java Temurin listo")
    return final


def resolve_java(settings: dict, major: int, on_progress=None, on_status=None,
                 cancel_event=None) -> Path:
    if settings.get("java_mode") == "custom":
        raw = (settings.get("java_path") or "").strip().strip('"')
        if not raw:
            raise RuntimeError("Elige una ruta de Java personalizada en Ajustes")
        path = Path(raw)
        java_exe = find_java_in(path) if path.is_dir() else path
        if not java_exe or not java_exe.is_file():
            raise RuntimeError(f"La ruta de Java no es valida: {raw}")
        if not java_version(java_exe):
            raise RuntimeError("Ese Java no pudo ejecutarse o no es compatible")
        if on_progress:
            on_progress(1.0, "Java personalizado listo")
        return java_exe
    return ensure_temurin(major, on_progress=on_progress,
                          on_status=on_status, cancel_event=cancel_event)
