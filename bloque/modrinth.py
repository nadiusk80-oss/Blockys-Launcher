from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path
from urllib.parse import quote, urlencode

from . import instances, net, paths

API = "https://api.modrinth.com/v2"

PROJECT_TYPES = {"mod", "modpack", "resourcepack", "shader", "datapack"}
KIND_FOLDERS = {"mod": "mods", "resourcepack": "resourcepacks",
                "shader": "shaderpacks"}
LOADER_CATEGORIES = {"fabric": "fabric", "quilt": "quilt", "forge": "forge",
                     "neoforge": "neoforge"}


class ModrinthError(Exception):
    pass


def _facets(project_type: str, loader: str, game_version: str) -> list[list[str]]:
    facets = [[f"project_type:{project_type}"]]
    if game_version:
        facets.append([f"versions:{game_version}"])
    if project_type == "mod" and loader in LOADER_CATEGORIES:
        if loader == "quilt":
            facets.append(["categories:quilt", "categories:fabric"])
        else:
            facets.append([f"categories:{LOADER_CATEGORIES[loader]}"])
    return facets


def search(query: str, project_type: str = "mod", loader: str = "",
           game_version: str = "", limit: int = 20, offset: int = 0,
           index: str = "") -> dict:
    if index not in ("relevance", "downloads", "follows", "newest",
                     "updated"):
        index = "relevance" if query else "downloads"
    params = {
        "query": query or "",
        "facets": json.dumps(_facets(project_type, loader, game_version),
                             separators=(",", ":")),
        "limit": str(max(1, min(50, limit))),
        "offset": str(max(0, offset)),
        "index": index,
    }
    url = f"{API}/search?{urlencode(params)}"
    try:
        data = net.http_json(url)
    except net.HttpError as exc:
        raise ModrinthError(f"Modrinth respondio {exc.status}") from exc
    except net.ConnectionError_ as exc:
        raise ModrinthError(f"Sin conexion con Modrinth: {exc}") from exc
    if not isinstance(data, dict):
        raise ModrinthError("Respuesta invalida de Modrinth")
    return data


def _compatible_versions(project_id: str, loader: str, game_version: str) -> list[dict]:
    params = {}
    if loader in LOADER_CATEGORIES:
        loaders = [LOADER_CATEGORIES[loader]]
        if loader == "quilt":
            loaders.append("fabric")
        params["loaders"] = json.dumps(loaders)
    if game_version:
        params["game_versions"] = json.dumps([game_version])
    query = f"?{urlencode(params)}" if params else ""
    try:
        data = net.http_json(f"{API}/project/{quote(project_id)}/version{query}")
    except net.HttpError as exc:
        raise ModrinthError(f"Modrinth respondio {exc.status}") from exc
    if not isinstance(data, list) or not data:
        raise ModrinthError(
            "No hay una version compatible con este cargador y esta version de Minecraft")
    return data


def _local_hashes(folder: Path) -> set[str]:
    hashes: set[str] = set()
    try:
        files = list(folder.iterdir())
    except OSError:
        return hashes
    for path in files:
        if not path.is_file() or path.name.startswith("."):
            continue
        if not path.name.lower().endswith((".jar", ".jar.disabled", ".zip",
                                           ".zip.disabled")):
            continue
        try:
            hashes.add(_file_sha1(path))
        except OSError:
            continue
    return hashes


def _version_details(version_id: str) -> dict | None:
    try:
        data = net.http_json(f"{API}/version/{quote(str(version_id))}")
    except (net.HttpError, net.ConnectionError_):
        return None
    return data if isinstance(data, dict) else None


def _install_version(version: dict, instance: dict, folder: str,
                     on_status=None, cancel_event=None, seen=None,
                     installed: set[str] | None = None,
                     depth: int = 0) -> Path | None:
    seen = seen or set()
    installed = installed if installed is not None else set()
    files = version.get("files") or []
    file = next((item for item in files if item.get("primary")),
                files[0] if files else None)
    if not file or not file.get("url"):
        return None
    hashes = file.get("hashes") or {}
    hash_value = str(hashes.get("sha1") or "").lower()
    filename = Path(file.get("filename") or "download.jar").name
    target_dir = instances_instance_dir(instance) / folder
    target_dir.mkdir(parents=True, exist_ok=True)
    dest = target_dir / filename
    if hash_value and hash_value in installed:
        return dest
    if on_status:
        on_status(f"Descargando {filename}...")
    try:
        net.download_one(file["url"], dest, sha1=hashes.get("sha1"),
                         sha256=hashes.get("sha256"), size=file.get("size"),
                         cancel_event=cancel_event)
    except net.DownloadError as exc:
        raise ModrinthError(f"Descarga fallida: {exc}") from exc
    if hash_value:
        installed.add(hash_value)

    if depth >= 4 or folder != "mods":
        return dest
    for dependency in version.get("dependencies") or []:
        if not isinstance(dependency, dict):
            continue
        if dependency.get("dependency_type") != "required":
            continue
        dependency_version = None
        version_id = dependency.get("version_id")
        if version_id:
            if version_id in seen:
                continue
            seen.add(version_id)
            dependency_version = _version_details(version_id)
        elif dependency.get("project_id"):
            project_id = str(dependency["project_id"])
            if project_id in seen:
                continue
            seen.add(project_id)
            try:
                choices = _compatible_versions(
                    project_id, instance.get("loader", "vanilla"),
                    str(instance.get("version") or ""))
            except ModrinthError:
                choices = []
            if choices:
                dependency_version = choices[0]
        if dependency_version:
            try:
                _install_version(dependency_version, instance, folder,
                                 on_status=on_status, cancel_event=cancel_event,
                                 seen=seen, installed=installed,
                                 depth=depth + 1)
            except ModrinthError as exc:
                if on_status:
                    on_status(f"Dependencia omitida: {exc}")
    return dest


def install(project_id: str, instance: dict, project_type: str = "mod",
            on_status=None, cancel_event=None) -> Path:
    folder = KIND_FOLDERS.get(project_type)
    if not folder:
        raise ModrinthError("Ese tipo de proyecto no se puede instalar aqui")
    loader = instance.get("loader", "vanilla")
    versions = _compatible_versions(
        project_id, loader if project_type == "mod" else "",
        str(instance.get("version") or ""))
    target_dir = instances_instance_dir(instance) / folder
    target_dir.mkdir(parents=True, exist_ok=True)
    result = _install_version(versions[0], instance, folder,
                              on_status=on_status, cancel_event=cancel_event,
                              installed=_local_hashes(target_dir))
    if result is None:
        raise ModrinthError("La version elegida no tiene un archivo descargable")
    return result


def instances_instance_dir(instance: dict) -> Path:
    custom = (instance.get("game_dir") or "").strip()
    if custom:
        return Path(custom)
    return paths.INSTANCES_DIR / instance["id"]


def _file_sha1(path: Path) -> str:
    import hashlib
    digest = hashlib.sha1()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(262144)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def check_updates(instance: dict, project_type: str = "mod",
                  on_status=None, cancel_event=None) -> list[Path]:
    folder = KIND_FOLDERS.get(project_type)
    if not folder:
        raise ModrinthError("Ese tipo de proyecto no admite actualizaciones")
    root = instances_instance_dir(instance) / folder
    if not root.is_dir():
        return []
    local: dict[str, Path] = {}
    for path in root.iterdir():
        if not path.is_file() or path.name.startswith("."):
            continue
        if not path.name.lower().endswith((".jar", ".jar.disabled", ".zip",
                                           ".zip.disabled")):
            continue
        try:
            local[_file_sha1(path)] = path
        except OSError:
            continue
    if not local:
        return []
    loader = instance.get("loader", "vanilla")
    body = {
        "hashes": list(local.keys()),
        "algorithm": "sha1",
    }
    if loader in LOADER_CATEGORIES:
        loaders = [LOADER_CATEGORIES[loader]]
        if loader == "quilt":
            loaders.append("fabric")
        body["loaders"] = loaders
    game_version = str(instance.get("version") or "")
    if game_version:
        body["game_versions"] = [game_version]
    data = json.dumps(body).encode("utf-8")
    if on_status:
        on_status("Consultando actualizaciones en Modrinth...")
    try:
        response = net.http_json(f"{API}/version_files/update", data=data,
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    except net.HttpError as exc:
        raise ModrinthError(f"Modrinth respondio {exc.status}") from exc
    except net.ConnectionError_ as exc:
        raise ModrinthError(f"Sin conexion con Modrinth: {exc}") from exc
    updated: list[Path] = []
    for old_hash, version in (response or {}).items():
        old_path = local.get(old_hash)
        if old_path is None:
            continue
        files = version.get("files") or []
        file = next((item for item in files if item.get("primary")),
                    files[0] if files else None)
        if not file or not file.get("url"):
            continue
        hashes = file.get("hashes") or {}
        if hashes.get("sha1") and hashes["sha1"].lower() == old_hash.lower():
            continue
        filename = Path(file.get("filename") or old_path.name).name
        if (old_path.name.lower().endswith(".disabled")
                and not filename.lower().endswith(".disabled")):
            filename += ".disabled"
        dest = old_path.with_name(filename)
        try:
            net.download_one(file["url"], dest, sha1=hashes.get("sha1"),
                             sha256=hashes.get("sha256"),
                             size=file.get("size"),
                             cancel_event=cancel_event)
            if dest != old_path:
                try:
                    old_path.unlink()
                except OSError:
                    pass
            updated.append(dest)
        except (OSError, net.DownloadError):
            continue
    return updated


def is_mrpack(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as archive:
            return "modrinth.index.json" in archive.namelist()
    except (OSError, zipfile.BadZipFile):
        return False


def _extract_overrides(archive: zipfile.ZipFile, prefix: str, target: Path) -> None:
    root = target.resolve()
    for name in archive.namelist():
        if not name.startswith(prefix) or name.endswith("/"):
            continue
        relative = name[len(prefix):]
        destination = (target / relative).resolve()
        if root != destination and root not in destination.parents:
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(name) as src, open(destination, "wb") as out:
            shutil.copyfileobj(src, out)


def import_mrpack(source: Path, store: instances.InstanceStore,
                  name: str | None = None, on_status=None,
                  on_progress=None, cancel_event=None) -> dict:
    source = Path(source)
    try:
        archive = zipfile.ZipFile(source)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ModrinthError("El modpack no es un .mrpack valido") from exc
    with archive:
        names = archive.namelist()
        if "modrinth.index.json" not in names:
            raise ModrinthError("El archivo no contiene modrinth.index.json")
        try:
            index = json.loads(archive.read("modrinth.index.json").decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ModrinthError("modrinth.index.json invalido") from exc
        deps = index.get("dependencies") or {}
        game = str(deps.get("minecraft") or "")
        if not game:
            raise ModrinthError("El modpack no indica la version de Minecraft")
        loader = "vanilla"
        loader_version = ""
        for key, value in (("fabric-loader", "fabric"), ("quilt-loader", "quilt"),
                           ("forge", "forge"), ("neoforge", "neoforge")):
            if deps.get(key):
                loader = value
                loader_version = str(deps[key])
                break
        instance = store.create(name or index.get("name") or source.stem,
                                game, loader)
        instance["loader_version"] = loader_version
        store.ensure_dirs(instance)
        folder = store.game_dir(instance)
        files = index.get("files") or []
        try:
            for position, entry in enumerate(files):
                if cancel_event is not None and cancel_event.is_set():
                    raise net.Cancelled()
                env = (entry.get("env") or {}).get("client")
                if env == "unsupported":
                    continue
                relative = Path(str(entry.get("path") or "")).as_posix()
                if not relative:
                    continue
                target = (folder / relative).resolve()
                if folder.resolve() not in target.parents:
                    continue
                downloads = entry.get("downloads") or []
                if not downloads:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                hashes = entry.get("hashes") or {}
                size = entry.get("fileSize")
                if on_status:
                    on_status(f"Modpack: {Path(relative).name}")
                net.download_one(downloads[0], target, sha1=hashes.get("sha1"),
                                 sha256=hashes.get("sha256"), size=size,
                                 cancel_event=cancel_event)
                if on_progress and files:
                    on_progress((position + 1) / len(files), "Descargando modpack")
            if any(name.startswith("overrides/") for name in names):
                _extract_overrides(archive, "overrides/", folder)
            if any(name.startswith("client-overrides/") for name in names):
                _extract_overrides(archive, "client-overrides/", folder)
            store.ensure_dirs(instance)
            store.save()
            return store.by_id(instance["id"]) or instance
        except Exception:
            store.remove(instance["id"])
            raise
