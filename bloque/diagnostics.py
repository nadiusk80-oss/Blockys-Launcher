from __future__ import annotations

import json
import os
import platform
import re
import shutil
import sys
import threading
import time
import traceback
import zipfile
from pathlib import Path

from . import __version__, paths

MAX_LOG_BYTES = 4 * 1024 * 1024

_SECRET_PATTERNS = (
    (re.compile(r"(access_token|refresh_token|accessToken|Authorization)"
                r"(\s*[:=]\s*)['\"]?([^\s'\",}]+)", re.IGNORECASE), r"\1\2***"),
    (re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE), "Bearer ***"),
)

_LOG_RULES = (
    {
        "tokens": ("outofmemoryerror", "java heap space", "gc overhead limit"),
        "title": "Memoria insuficiente",
        "hint": "Subí la memoria de la instancia en General o quitá mods pesados. "
                "No asignes más de la mitad de tu RAM total.",
    },
    {
        "tokens": ("unsupportedclassversionerror", "compiled by a more recent version"),
        "title": "Versión de Java incorrecta",
        "hint": "La instancia necesita otra versión de Java. En General elegí "
                "'Temurin automático' o apuntá a un java.exe compatible.",
    },
    {
        "tokens": ("could not find or load main class", "noclassdeffounderror",
                   "classnotfoundexception"),
        "title": "Archivos del juego incompletos",
        "hint": "Faltan librerías o el JAR del cliente. Volvé a iniciar la "
                "instancia para que Blockys repare la descarga.",
    },
    {
        "tokens": ("missing or unsupported mandatory dependencies",
                   "incompatible mod set", "mod resolution encountered",
                   "requires version"),
        "title": "Conflicto de mods",
        "hint": "Un mod necesita una dependencia o versión distinta. Revisá la "
                "pestaña Mods y desactivá el mod que menciona el registro.",
    },
    {
        "tokens": ("mixin apply failed", "mixintransformererror",
                   "mixinapplyerror"),
        "title": "Conflicto de Mixin",
        "hint": "Dos mods modifican la misma clase. Actualizá o desactivá uno "
                "de los mods de la pila de error.",
    },
    {
        "tokens": ("duplicate mods", "duplicatemodsexception"),
        "title": "Mods duplicados",
        "hint": "Hay dos archivos del mismo mod en la carpeta mods. Eliminá la "
                "versión vieja y dejá una sola.",
    },
    {
        "tokens": ("glfw error", "failed to create glfw window",
                   "pixel format not accelerated", "opengl", "wgl"),
        "title": "Problema gráfico",
        "hint": "Actualizá los controladores de la placa de video y evitá "
                "forzar OpenGL por software. En equipos viejos probá una "
                "versión y mods más livianos.",
    },
    {
        "tokens": ("accessdeniedexception", "permission denied", "access is denied"),
        "title": "Permisos de archivos",
        "hint": "El antivirus o Windows bloqueó la carpeta de la instancia. "
                "Agregá una exclusión para %APPDATA%\\BloqueLauncher.",
    },
    {
        "tokens": ("java.lang.nosuchmethoderror", "java.lang.noclassdeffounderror",
                   "abstractmethoderror"),
        "title": "Mods incompatibles",
        "hint": "Un mod fue compilado para otra versión de Minecraft o del "
                "cargador. Actualizalo o quitá el mod indicado.",
    },
    {
        "tokens": ("minecraft crash report", "caught exception", "fatal error"),
        "title": "Cierre inesperado",
        "hint": "Revisá la pestaña Consola y el crash report de la instancia. "
                "Si el problema empezó después de instalar mods, desactivalos "
                "y probá de nuevo.",
    },
)


def redact(text: str) -> str:
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def detect_issues(text: str) -> list[dict]:
    lowered = (text or "").lower()
    found: list[dict] = []
    seen: set[str] = set()
    for rule in _LOG_RULES:
        if rule["title"] in seen:
            continue
        if any(token in lowered for token in rule["tokens"]):
            found.append({"title": rule["title"], "hint": rule["hint"]})
            seen.add(rule["title"])
        if len(found) >= 4:
            break
    return found


def analyze_log(path: Path) -> list[dict]:
    path = Path(path)
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - MAX_LOG_BYTES))
            text = handle.read().decode("utf-8", "replace")
    except OSError:
        return []
    return detect_issues(text)


def latest_game_log() -> Path | None:
    try:
        files = [path for path in paths.LOGS_DIR.glob("game-*.log")
                 if path.is_file()]
        return max(files, key=lambda path: path.stat().st_mtime) if files else None
    except OSError:
        return None


def _java_report() -> list[str]:
    lines = []
    try:
        from . import java
    except Exception as exc:
        return [f"  No se pudo consultar Java: {exc}"]
    for major in java.JAVA_MAJORS:
        try:
            result = java.installed_runtime(major)
        except Exception as exc:
            lines.append(f"  Java {major}: error ({exc})")
            continue
        lines.append(f"  Java {major}: {'instalado' if result else 'no instalado'}")
    return lines


def _settings_report(settings: dict) -> list[str]:
    keys = ("memory_mb", "game_dir", "java_mode", "java_path", "resolution_width",
            "resolution_height", "custom_resolution", "copy_skin_mod",
            "aikar_flags", "version_type", "instance_sort")
    lines = []
    for key in keys:
        value = settings.get(key, "")
        if key == "client_id" and value:
            value = "configurado"
        lines.append(f"  {key}: {value}")
    return lines


def build_report(settings: dict, instance_store, manifest: dict | None = None,
                 latest_log: Path | None = None) -> str:
    disk = ""
    try:
        usage = shutil.disk_usage(paths.APP_DIR)
        disk = (f"  Libre: {usage.free // (1024 ** 3)} GB de "
                f"{usage.total // (1024 ** 3)} GB")
    except OSError:
        disk = "  No disponible"

    lines = [
        "Blockys - Diagnóstico",
        "=" * 52,
        f"Versión: {__version__}",
        f"Fecha: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Empaquetado: {'sí' if getattr(sys, 'frozen', False) else 'no'}",
        "",
        "Sistema",
        f"  {platform.platform()}",
        f"  Arquitectura: {platform.machine()} "
        f"({('64' if sys.maxsize > 2**32 else '32')} bits de proceso)",
        f"  Python: {platform.python_version()}",
        f"  Ejecutable: {sys.executable}",
        "",
        "Carpetas",
        f"  Datos: {paths.APP_DIR}",
        f"  Instancias: {paths.INSTANCES_DIR}",
        f"  Versiones: {paths.VERSIONS_DIR}",
        f"  Java: {paths.RUNTIME_DIR}",
        f"  Logs: {paths.LOGS_DIR}",
        disk,
        "",
        "Ajustes",
        *_settings_report(settings),
        "",
        "Java",
        *_java_report(),
        "",
        "Instancias",
    ]
    instances = getattr(instance_store, "instances", [])
    if not instances:
        lines.append("  (ninguna)")
    for instance in instances:
        loader = instance.get("loader", "vanilla")
        lines.append(
            f"  - {instance.get('name', '')} | {loader} "
            f"{instance.get('version', '')} | "
            f"{instance.get('resolved_version') or 'sin preparar'}")
        lines.append(f"    Carpeta: {Path(instance_store.game_dir(instance))}")
    lines.append("")
    lines.append("Manifiesto")
    if manifest:
        versions = manifest.get("versions", [])
        lines.append(f"  Versiones disponibles: {len(versions)}")
        lines.append(f"  Última: {versions[0].get('id', '') if versions else ''}")
    else:
        lines.append("  No cargado en esta sesión")
    lines.append("")
    lines.append("Último registro del juego")
    if latest_log and latest_log.is_file():
        try:
            size = latest_log.stat().st_size
        except OSError:
            size = 0
        lines.append(f"  {latest_log.name} ({size} bytes)")
        issues = analyze_log(latest_log)
        if issues:
            lines.append("  Problemas detectados:")
            for issue in issues:
                lines.append(f"    - {issue['title']}: {issue['hint']}")
        else:
            lines.append("  Sin errores conocidos detectados.")
    else:
        lines.append("  (sin registros)")
    lines.append("")
    return "\n".join(lines)


def _copy_log(archive: zipfile.ZipFile, path: Path, name: str) -> None:
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - MAX_LOG_BYTES))
            text = handle.read().decode("utf-8", "replace")
    except OSError:
        return
    archive.writestr(name, redact(text))


def export_report(dest: Path, settings: dict, instance_store,
                  manifest: dict | None = None) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    log = latest_game_log()
    report = build_report(settings, instance_store, manifest, log)
    temporary = dest.with_name(dest.name + ".part")
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("diagnostico.txt", redact(report))
            safe_settings = dict(settings)
            if safe_settings.get("client_id"):
                safe_settings["client_id"] = "configurado"
            archive.writestr("ajustes.json",
                             json.dumps(safe_settings, indent=2, ensure_ascii=False))
            summaries = []
            for instance in getattr(instance_store, "instances", []):
                summaries.append({
                    "name": instance.get("name", ""),
                    "version": instance.get("version", ""),
                    "loader": instance.get("loader", ""),
                    "loader_version": instance.get("loader_version", ""),
                    "resolved_version": instance.get("resolved_version", ""),
                    "game_dir": str(instance_store.game_dir(instance)),
                })
            archive.writestr("instancias.json",
                             json.dumps(summaries, indent=2, ensure_ascii=False))
            if log and log.is_file():
                _copy_log(archive, log, f"logs/{log.name}")
            try:
                crashes = sorted(paths.LOGS_DIR.glob("crash-*.log"),
                                 key=lambda item: item.stat().st_mtime,
                                 reverse=True)[:3]
            except OSError:
                crashes = []
            for crash in crashes:
                _copy_log(archive, crash, f"logs/{crash.name}")
        os.replace(temporary, dest)
    except Exception:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise
    return dest


def record_crash(exc_type, exc, tb, context: str = "") -> Path | None:
    try:
        paths.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        path = paths.LOGS_DIR / time.strftime("crash-%Y%m%d-%H%M%S.log")
        body = [
            f"Blockys {__version__} - error no controlado",
            f"Fecha: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"Contexto: {context or 'principal'}",
            f"Sistema: {platform.platform()}",
            f"Python: {platform.python_version()}",
            "",
        ]
        body.extend(traceback.format_exception(exc_type, exc, tb))
        path.write_text(redact("".join(body)), encoding="utf-8")
        try:
            crashes = sorted(paths.LOGS_DIR.glob("crash-*.log"),
                             key=lambda item: item.stat().st_mtime,
                             reverse=True)
        except OSError:
            crashes = []
        for old in crashes[10:]:
            try:
                old.unlink()
            except OSError:
                pass
        return path
    except Exception:
        return None


def install_exception_hooks() -> None:
    previous_thread = threading.excepthook

    def thread_hook(args):
        if args.exc_type is SystemExit:
            return
        record_crash(args.exc_type, args.exc_value, args.exc_traceback,
                     f"hilo {getattr(args.thread, 'name', '')}")
        previous_thread(args)

    threading.excepthook = thread_hook
