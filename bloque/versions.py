from __future__ import annotations

import copy
import platform
import re
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from . import net, paths
from .util import load_json, safe_extract, save_json

MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
RESOURCES_URL = "https://resources.download.minecraft.net"

OS_NAME = {"win32": "windows", "darwin": "osx"}.get(sys.platform, "linux")
IS_64 = sys.maxsize > 2**32
NATIVE_ARCH = "64" if IS_64 else "32"


def default_features(settings: dict | None = None) -> dict:
    features = {
        "is_demo_user": False,
        "has_custom_resolution": False,
        "has_quick_plays_support": False,
        "is_quick_play_singleplayer": False,
        "is_quick_play_multiplayer": False,
        "is_quick_play_realms": False,
    }
    if settings:
        features["has_custom_resolution"] = bool(settings.get("custom_resolution"))
        quick_type = settings.get("quick_play_type", "none")
        target = str(settings.get("quick_play_target") or "").strip()
        if target and quick_type in ("world", "server", "realms"):
            features["has_quick_plays_support"] = True
            features["is_quick_play_singleplayer"] = quick_type == "world"
            features["is_quick_play_multiplayer"] = quick_type == "server"
            features["is_quick_play_realms"] = quick_type == "realms"
    return features


def _os_matches(rule_os: dict) -> bool:
    if rule_os.get("name") and rule_os["name"] != OS_NAME:
        return False
    arch = rule_os.get("arch")
    if arch:
        machine = platform.machine().lower()
        is_arm = machine in ("arm64", "aarch64")
        if arch == "x86" and IS_64:
            return False
        if arch == "arm64" and not is_arm:
            return False
        if arch in ("x86_64", "amd64") and (is_arm or not IS_64):
            return False
    version = rule_os.get("version")
    if version:
        try:
            if not re.search(version, platform.version()):
                return False
        except re.error:
            return False
    return True


def rules_allow(rules, features: dict | None = None) -> bool:
    if not rules:
        return True
    features = features or {}
    allowed = False
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        if rule.get("os") and not _os_matches(rule["os"]):
            continue
        rule_features = rule.get("features")
        if rule_features:
            if any(features.get(key, False) != value for key, value in rule_features.items()):
                continue
        allowed = rule.get("action") == "allow"
    return allowed


def load_manifest(force: bool = False) -> dict:
    cached = paths.MANIFEST_FILE
    cached_data = load_json(cached, {})
    if not force and cached_data.get("versions"):
        try:
            if time.time() - cached.stat().st_mtime < 900:
                return cached_data
        except OSError:
            pass
    try:
        data = net.http_json(MANIFEST_URL)
        if data.get("versions"):
            save_json(cached, data)
            return data
    except Exception:
        if cached_data.get("versions"):
            return cached_data
        raise
    if cached_data.get("versions"):
        return cached_data
    raise RuntimeError("El manifiesto de versiones llego vacio")


def find_entry(manifest: dict, version_id: str) -> dict | None:
    for entry in manifest.get("versions", []):
        if entry.get("id") == version_id:
            return entry
    return None


def get_version_json(entry: dict) -> dict:
    version_id = entry["id"]
    folder = paths.VERSIONS_DIR / version_id
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{version_id}.json"
    cached = load_json(dest, {})
    if cached.get("id") == version_id:
        return cached
    url = entry.get("url")
    if not url:
        raise RuntimeError(f"Falta el JSON de la version {version_id}")
    net.download_one(url, dest, sha1=entry.get("sha1"), size=entry.get("size"))
    data = load_json(dest, {})
    if not data:
        raise RuntimeError(f"No se pudo leer el JSON de la version {version_id}")
    return data


def read_version_json(version_id: str) -> dict | None:
    dest = paths.VERSIONS_DIR / version_id / f"{version_id}.json"
    data = load_json(dest, {})
    return data if data.get("id") else None


def _coordinate_key(lib: dict) -> str:
    name = (lib.get("name") or "").split("@", 1)[0]
    parts = name.split(":")
    if len(parts) >= 3:
        classifier = parts[3] if len(parts) > 3 else ""
        return f"{parts[0]}:{parts[1]}:{classifier}"
    artifact = ((lib.get("downloads") or {}).get("artifact") or {})
    path = artifact.get("path") or ""
    if path:
        return path
    return ""


def _merge_arguments(parent: dict, child: dict) -> dict | None:
    parent_args = parent.get("arguments")
    child_args = child.get("arguments")
    if not parent_args and not child_args:
        return None
    merged = {}
    for section in ("game", "jvm"):
        parent_list = (parent_args or {}).get(section) or []
        child_list = (child_args or {}).get(section) or []
        if parent_list or child_list:
            merged[section] = list(parent_list) + list(child_list)
    return merged or None


def merge_version(child: dict, parent: dict) -> dict:
    merged = copy.deepcopy(parent)
    for key, value in child.items():
        if key in ("libraries", "arguments", "downloads"):
            continue
        merged[key] = copy.deepcopy(value)

    arguments = _merge_arguments(parent, child)
    if arguments is not None:
        merged["arguments"] = arguments
    elif "arguments" in merged and not child.get("arguments"):
        pass

    child_downloads = child.get("downloads")
    if isinstance(child_downloads, dict) and child_downloads:
        merged["downloads"] = copy.deepcopy(child_downloads)

    libraries: dict[str, dict] = {}
    for index, lib in enumerate(parent.get("libraries") or []):
        key = _coordinate_key(lib) or f"_p{index}"
        libraries[key] = copy.deepcopy(lib)
    for index, lib in enumerate(child.get("libraries") or []):
        key = _coordinate_key(lib) or f"_c{index}"
        libraries[key] = copy.deepcopy(lib)
    merged["libraries"] = list(libraries.values())
    return merged


def resolve_version(version_data: dict, depth: int = 0) -> dict:
    parent_id = version_data.get("inheritsFrom")
    if not parent_id or depth >= 5:
        return copy.deepcopy(version_data)
    parent_data = read_version_json(parent_id)
    if not parent_data:
        manifest = load_manifest()
        entry = find_entry(manifest, parent_id)
        if not entry:
            raise RuntimeError(f"Falta la version base {parent_id}")
        parent_data = get_version_json(entry)
    parent_data = resolve_version(parent_data, depth + 1)
    merged = merge_version(version_data, parent_data)
    merged["id"] = version_data.get("id") or merged.get("id")
    merged["_base_id"] = parent_data.get("id") or parent_id
    return merged


def required_java(version_data: dict) -> int:
    info = version_data.get("javaVersion") or {}
    try:
        return int(info.get("majorVersion") or 8)
    except (TypeError, ValueError):
        return 8


def _scale(on_progress, start: float, end: float, label: str):
    if on_progress is None:
        return None

    def callback(done, total, files_done, files_total):
        if total:
            ratio = done / total
        elif files_total:
            ratio = files_done / files_total
        else:
            ratio = 1.0
        ratio = min(max(ratio, 0.0), 1.0)
        on_progress(start + (end - start) * ratio, label)

    return callback


def _maven_artifact(lib: dict, classifier: str = "") -> dict:
    name = lib.get("name") or ""
    extension = "jar"
    if "@" in name:
        name, extension = name.rsplit("@", 1)
    parts = name.split(":")
    if len(parts) < 3:
        return {}
    group, artifact, version = parts[:3]
    if not classifier and len(parts) > 3:
        classifier = parts[3]
    filename = f"{artifact}-{version}"
    if classifier:
        filename += f"-{classifier}"
    filename += f".{extension}"
    path = f"{group.replace('.', '/')}/{artifact}/{version}/{filename}"
    base = (lib.get("url") or "").strip()
    if not base:
        return {"path": path}
    url = base.rstrip("/") + "/" + path
    return {"path": path, "url": url, "size": None}


def _library_artifact(lib: dict) -> dict:
    downloads = lib.get("downloads") or {}
    artifact = downloads.get("artifact") or {}
    if artifact.get("path"):
        if not artifact.get("url"):
            fallback = _maven_artifact(lib)
            if fallback.get("url"):
                artifact = {**artifact, "url": fallback["url"]}
        return artifact
    if lib.get("name") and lib.get("url"):
        return _maven_artifact(lib)
    return {}


def _native_classifier(lib: dict, classifier: str) -> dict:
    downloads = lib.get("downloads") or {}
    info = (downloads.get("classifiers") or {}).get(classifier) or {}
    if info.get("path"):
        return info
    if lib.get("url") and lib.get("name"):
        return _maven_artifact(lib, classifier)
    return {}


def _library_tasks(version_data: dict, features: dict):
    tasks: list[net.Task] = []
    classpath: list[Path] = []
    natives: list[Path] = []
    for lib in version_data.get("libraries", []):
        if not rules_allow(lib.get("rules"), features):
            continue
        name = lib.get("name") or ""
        if "natives-" in name:
            if "arm64" in name and platform.machine().lower() not in ("arm64", "aarch64"):
                continue
            if re.search(r"-natives-[a-z0-9]*-?x86(?![_-]?64)", name) and IS_64:
                continue
        artifact = _library_artifact(lib)
        if artifact.get("path"):
            dest = paths.LIBRARIES_DIR / artifact["path"]
            if artifact.get("url"):
                tasks.append(net.Task(artifact["url"], dest, artifact.get("sha1"),
                                      None, artifact.get("size")))
            classpath.append(dest)
        natives_map = lib.get("natives") or {}
        classifier = natives_map.get(OS_NAME)
        if classifier:
            classifier = classifier.replace("${arch}", NATIVE_ARCH)
            info = _native_classifier(lib, classifier)
            if info.get("path"):
                dest = paths.LIBRARIES_DIR / info["path"]
                if info.get("url"):
                    tasks.append(net.Task(info["url"], dest, info.get("sha1"),
                                          None, info.get("size")))
                natives.append(dest)
    return tasks, classpath, natives


@dataclass
class InstallPlan:
    version_id: str
    version_dir: Path
    client_jar: Path
    classpath: list[Path]
    natives_dir: Path
    assets_dir: Path
    asset_index_id: str
    asset_index_path: Path | None
    virtual_dir: Path | None
    log_config: Path | None
    java_major: int
    version_type: str
    main_class: str
    data: dict


def _copy_asset(source: Path, target: Path) -> None:
    try:
        if target.exists() and target.stat().st_size == source.stat().st_size:
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    except OSError:
        pass


def install(entry: dict, version_data: dict, settings: dict, features: dict,
            on_progress=None, on_status=None, cancel_event=None) -> InstallPlan:
    paths.ensure_dirs()
    version_data = resolve_version(version_data)
    version_id = version_data.get("id") or entry["id"]
    version_dir = paths.VERSIONS_DIR / version_id
    version_dir.mkdir(parents=True, exist_ok=True)

    base_tasks: list[net.Task] = []
    client_info = (version_data.get("downloads") or {}).get("client") or {}
    child_jar = version_dir / f"{version_id}.jar"
    jar_id = version_data.get("jar") or version_data.get("inheritsFrom") or ""
    if child_jar.is_file():
        client_jar = child_jar
    elif jar_id:
        client_jar = paths.VERSIONS_DIR / str(jar_id) / f"{jar_id}.jar"
    else:
        client_jar = child_jar
    if client_info.get("url") and client_jar == child_jar:
        base_tasks.append(net.Task(client_info["url"], child_jar, client_info.get("sha1"),
                                   None, client_info.get("size")))
    elif client_info.get("url") and not client_jar.is_file() and not jar_id:
        base_tasks.append(net.Task(client_info["url"], child_jar, client_info.get("sha1"),
                                   None, client_info.get("size")))
        client_jar = child_jar
    elif jar_id and client_info.get("url") and not client_jar.is_file():
        base_tasks.append(net.Task(client_info["url"], client_jar, client_info.get("sha1"),
                                   None, client_info.get("size")))

    lib_tasks, classpath, natives_jars = _library_tasks(version_data, features)
    base_tasks.extend(lib_tasks)

    log_config = None
    log_info = ((version_data.get("logging") or {}).get("client") or {}).get("file") or {}
    if log_info.get("url"):
        target = paths.ASSETS_DIR / "log_configs" / (log_info.get("id") or "client.xml")
        base_tasks.append(net.Task(log_info["url"], target, log_info.get("sha1"),
                                   None, log_info.get("size")))
        log_config = target

    index_info = version_data.get("assetIndex") or {}
    index_id = version_data.get("assets") or index_info.get("id") or "legacy"
    index_path = None
    if index_info.get("url"):
        index_path = paths.ASSETS_DIR / "indexes" / f"{index_info.get('id', index_id)}.json"
        base_tasks.append(net.Task(index_info["url"], index_path, index_info.get("sha1"),
                                   None, index_info.get("size")))

    if on_status:
        on_status("Descargando cliente y bibliotecas...")
    net.download_many(base_tasks, workers=12,
                      on_progress=_scale(on_progress, 0.0, 0.25, "Bibliotecas"),
                      cancel_event=cancel_event)

    asset_count = 0
    index_data = load_json(index_path, {}) if index_path else {}
    objects = index_data.get("objects") or {}
    if objects:
        if on_status:
            on_status(f"Descargando {len(objects)} assets...")
        asset_tasks = []
        for name, obj in objects.items():
            digest = obj.get("hash")
            if not digest:
                continue
            dest = paths.ASSETS_DIR / "objects" / digest[:2] / digest
            asset_tasks.append(net.Task(f"{RESOURCES_URL}/{digest[:2]}/{digest}", dest,
                                        digest, None, obj.get("size")))
            asset_count += 1
        net.download_many(asset_tasks, workers=16,
                          on_progress=_scale(on_progress, 0.25, 0.9, "Assets"),
                          cancel_event=cancel_event)

    virtual_dir = None
    if objects:
        if on_status:
            on_status("Preparando assets...")
        objects_root = paths.ASSETS_DIR / "objects"
        if index_data.get("virtual"):
            virtual_dir = paths.ASSETS_DIR / "virtual" / str(index_id)
            for name, obj in objects.items():
                digest = obj.get("hash")
                if digest:
                    _copy_asset(objects_root / digest[:2] / digest, virtual_dir / name)
        if index_data.get("map_to_resources"):
            resources = Path(settings["game_dir"]) / "resources"
            for name, obj in objects.items():
                digest = obj.get("hash")
                if digest:
                    _copy_asset(objects_root / digest[:2] / digest, resources / name)
        if on_progress:
            on_progress(0.9, "Assets preparados")

    natives_dir = version_dir / "natives"
    natives_dir.mkdir(parents=True, exist_ok=True)
    if natives_jars:
        if on_status:
            on_status("Extrayendo natives...")
        for jar in natives_jars:
            if jar.exists():
                safe_extract(jar, natives_dir, skip_meta=True)
    if on_progress:
        on_progress(1.0, "Archivos listos")

    classpath = list(dict.fromkeys(classpath))
    if client_jar.exists() and client_jar not in classpath:
        classpath.append(client_jar)

    return InstallPlan(
        version_id=version_id,
        version_dir=version_dir,
        client_jar=client_jar,
        classpath=classpath,
        natives_dir=natives_dir,
        assets_dir=paths.ASSETS_DIR,
        asset_index_id=index_id,
        asset_index_path=index_path,
        virtual_dir=virtual_dir,
        log_config=log_config,
        java_major=required_java(version_data),
        version_type=version_data.get("type", "release"),
        main_class=version_data.get("mainClass", "net.minecraft.client.main.Main"),
        data=version_data,
    )
