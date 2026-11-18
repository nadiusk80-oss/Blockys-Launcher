from __future__ import annotations

import json
import shutil
import time
import uuid
import zipfile
from pathlib import Path

from . import paths
from .util import load_json, save_json

LOADERS = {
    "vanilla": "Vanilla",
    "fabric": "Fabric",
    "quilt": "Quilt",
    "forge": "Forge",
    "neoforge": "NeoForge",
}
LOADER_KEYS = {label.lower(): key for key, label in LOADERS.items()}

ICON_COLORS = ("#e2b25a", "#95c46a", "#d76f5c", "#7fb6d9", "#c39bd3",
               "#d9a24e", "#8fd3c1", "#b8b1a1")

MOD_SUFFIX = ".disabled"


class InstanceError(Exception):
    pass


def _clean_name(name: str) -> str:
    name = " ".join((name or "").split())
    return name[:48] or "Nueva instancia"


def _unique_name(store: list[dict], name: str) -> str:
    existing = {item.get("name", "").casefold() for item in store}
    if name.casefold() not in existing:
        return name
    for index in range(2, 1000):
        candidate = f"{name} {index}"
        if candidate.casefold() not in existing:
            return candidate
    return f"{name} {int(time.time())}"


def _default_instance(store: list[dict], name: str, version: str,
                      loader: str = "vanilla") -> dict:
    instance_id = uuid.uuid4().hex[:12]
    color = ICON_COLORS[len(store) % len(ICON_COLORS)]
    return {
        "id": instance_id,
        "name": _unique_name(store, _clean_name(name)),
        "version": version,
        "loader": loader if loader in LOADERS else "vanilla",
        "loader_version": "",
        "resolved_version": "",
        "game_dir": "",
        "memory_mb": 2048,
        "resolution_width": 1280,
        "resolution_height": 720,
        "custom_resolution": False,
        "java_mode": "inherit",
        "java_path": "",
        "aikar_flags": True,
        "icon": color,
        "icon_path": "",
        "group": "",
        "notes": "",
        "jvm_args": "",
        "game_args": "",
        "env_vars": "",
        "pre_launch": "",
        "post_exit": "",
        "quick_play_type": "none",
        "quick_play_target": "",
        "created": int(time.time()),
        "last_played": 0,
    }


class InstanceStore:
    def __init__(self):
        data = load_json(paths.INSTANCES_FILE, {})
        if not isinstance(data, dict):
            data = {}
        instances = data.get("instances")
        self.data = {
            "instances": [item for item in instances if isinstance(item, dict)]
            if isinstance(instances, list) else [],
            "selected": str(data.get("selected") or ""),
        }
        for instance in self.data["instances"]:
            self._normalize(instance)

    def _normalize(self, instance: dict) -> None:
        instance.setdefault("id", uuid.uuid4().hex[:12])
        instance.setdefault("name", "Instancia")
        instance.setdefault("version", "")
        if instance.get("loader") not in LOADERS:
            instance["loader"] = "vanilla"
        instance.setdefault("loader_version", "")
        instance.setdefault("resolved_version", "")
        instance.setdefault("game_dir", "")
        instance.setdefault("memory_mb", 2048)
        instance.setdefault("resolution_width", 1280)
        instance.setdefault("resolution_height", 720)
        instance.setdefault("custom_resolution", False)
        instance.setdefault("java_mode", "inherit")
        instance.setdefault("java_path", "")
        instance.setdefault("aikar_flags", True)
        instance.setdefault("icon", ICON_COLORS[0])
        instance.setdefault("icon_path", "")
        instance.setdefault("group", "")
        instance.setdefault("notes", "")
        instance.setdefault("jvm_args", "")
        instance.setdefault("game_args", "")
        instance.setdefault("env_vars", "")
        instance.setdefault("pre_launch", "")
        instance.setdefault("post_exit", "")
        if instance.get("quick_play_type") not in ("none", "world", "server",
                                                  "realms"):
            instance["quick_play_type"] = "none"
        instance.setdefault("quick_play_target", "")
        instance.setdefault("created", int(time.time()))
        instance.setdefault("last_played", 0)

    @property
    def instances(self) -> list[dict]:
        return self.data["instances"]

    def by_id(self, instance_id: str) -> dict | None:
        return next((item for item in self.instances
                     if item.get("id") == instance_id), None)

    def selected(self) -> dict | None:
        instance = self.by_id(self.data.get("selected", ""))
        if instance is None and self.instances:
            instance = self.instances[0]
        return instance

    def select(self, instance_id: str) -> None:
        if self.by_id(instance_id):
            self.data["selected"] = instance_id
            self.save()

    def clear_selection(self) -> None:
        self.data["selected"] = ""
        self.save()

    def create(self, name: str, version: str, loader: str = "vanilla",
               settings: dict | None = None) -> dict:
        if not version:
            raise InstanceError("Elige una versión de Minecraft")
        instance = _default_instance(self.instances, name, version, loader)
        if settings:
            instance["memory_mb"] = int(settings.get("memory_mb", 2048))
            instance["resolution_width"] = int(settings.get("resolution_width", 1280))
            instance["resolution_height"] = int(settings.get("resolution_height", 720))
            instance["custom_resolution"] = bool(settings.get("custom_resolution"))
            instance["aikar_flags"] = bool(settings.get("aikar_flags", True))
        self.instances.append(instance)
        self.data["selected"] = instance["id"]
        self.ensure_dirs(instance)
        self.save()
        return instance

    def duplicate(self, instance_id: str) -> dict | None:
        source = self.by_id(instance_id)
        if not source:
            return None
        copy = dict(source)
        copy["id"] = uuid.uuid4().hex[:12]
        copy["name"] = _unique_name(self.instances, f"{source['name']} copia")
        copy["game_dir"] = ""
        copy["created"] = int(time.time())
        copy["last_played"] = 0
        self.instances.append(copy)
        src_dir = self.game_dir(source)
        dst_dir = self.game_dir(copy)
        try:
            if src_dir.is_dir():
                shutil.copytree(src_dir, dst_dir, dirs_exist_ok=True)
        except OSError as exc:
            self.instances.remove(copy)
            raise InstanceError(f"No se pudo copiar la instancia: {exc}") from exc
        icon = Path(str(source.get("icon_path") or ""))
        if icon.is_file():
            target_icon = dst_dir / "blockys-icon.png"
            try:
                if not (icon.parent.resolve() == src_dir.resolve()
                        and icon.name == "blockys-icon.png"):
                    shutil.copy2(icon, target_icon)
                copy["icon_path"] = str(target_icon)
            except OSError:
                copy["icon_path"] = ""
        else:
            copy["icon_path"] = ""
        self.ensure_dirs(copy)
        self.data["selected"] = copy["id"]
        self.save()
        return copy

    def remove(self, instance_id: str) -> None:
        instance = self.by_id(instance_id)
        if not instance:
            return
        folder = self.game_dir(instance)
        self.instances.remove(instance)
        if self.data.get("selected") == instance_id:
            self.data["selected"] = self.instances[0]["id"] if self.instances else ""
        self.save()
        try:
            default_root = (paths.INSTANCES_DIR / instance["id"]).resolve()
            if folder.resolve() == default_root:
                shutil.rmtree(default_root, ignore_errors=True)
        except OSError:
            pass

    def game_dir(self, instance: dict) -> Path:
        custom = str(instance.get("game_dir") or "").strip()
        if custom:
            return Path(custom)
        return paths.INSTANCES_DIR / instance["id"]

    def ensure_dirs(self, instance: dict) -> Path:
        folder = self.game_dir(instance)
        try:
            for name in ("mods", "resourcepacks", "shaderpacks", "saves",
                         "screenshots", "config", "logs"):
                (folder / name).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise InstanceError(f"No se pudo crear la carpeta de la instancia: {exc}") from exc
        return folder

    def touch(self, instance: dict) -> None:
        instance["last_played"] = int(time.time())
        self.save()

    def save(self) -> None:
        save_json(paths.INSTANCES_FILE, self.data)

    # File management -------------------------------------------------
    def _folder(self, instance: dict, kind: str) -> Path:
        folder = self.game_dir(instance) / kind
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _safe(self, instance: dict, path: Path) -> Path:
        root = self.game_dir(instance).resolve()
        target = Path(path).resolve()
        if target != root and root not in target.parents:
            raise InstanceError("Archivo fuera de la instancia")
        return target

    def list_mods(self, instance: dict) -> list[dict]:
        folder = self._folder(instance, "mods")
        entries = []
        try:
            files = sorted(folder.iterdir(), key=lambda item: item.name.lower())
        except OSError:
            return entries
        for path in files:
            if not path.is_file():
                continue
            enabled = path.name.endswith(".jar") or path.name.endswith(".jar.disabled")
            if not enabled:
                continue
            disabled = path.name.endswith(MOD_SUFFIX)
            name = path.name[:-len(MOD_SUFFIX)] if disabled else path.name
            entries.append({"path": path, "name": name, "enabled": not disabled,
                            "size": path.stat().st_size})
        return entries

    def toggle_mod(self, instance: dict, path: Path) -> bool:
        target = self._safe(instance, path)
        if target.name.endswith(MOD_SUFFIX):
            new_path = target.with_name(target.name[:-len(MOD_SUFFIX)])
        else:
            new_path = target.with_name(target.name + MOD_SUFFIX)
        try:
            target.rename(new_path)
        except OSError as exc:
            raise InstanceError(f"No se pudo cambiar el mod: {exc}") from exc
        return not new_path.name.endswith(MOD_SUFFIX)

    def list_simple(self, instance: dict, kind: str,
                    suffixes: tuple[str, ...] | None = None) -> list[Path]:
        folder = self._folder(instance, kind)
        try:
            items = sorted(folder.iterdir(), key=lambda item: item.name.lower())
        except OSError:
            return []
        result = []
        for item in items:
            if not item.is_dir() and suffixes and not item.name.lower().endswith(suffixes):
                continue
            result.append(item)
        return result

    def add_files(self, instance: dict, kind: str, sources: list[Path]) -> int:
        folder = self._folder(instance, kind)
        added = 0
        for source in sources:
            source = Path(source)
            if not source.is_file():
                continue
            target = folder / source.name
            try:
                shutil.copyfile(source, target)
                added += 1
            except OSError as exc:
                raise InstanceError(f"No se pudo copiar {source.name}: {exc}") from exc
        return added

    def add_folder(self, instance: dict, kind: str, source: Path) -> bool:
        folder = self._folder(instance, kind)
        source = Path(source)
        if not source.is_dir():
            return False
        target = folder / source.name
        try:
            shutil.copytree(source, target, dirs_exist_ok=True)
            return True
        except OSError as exc:
            raise InstanceError(f"No se pudo copiar la carpeta: {exc}") from exc

    def delete_entry(self, instance: dict, path: Path) -> None:
        target = self._safe(instance, path)
        try:
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        except OSError as exc:
            raise InstanceError(f"No se pudo borrar: {exc}") from exc

    def worlds(self, instance: dict) -> list[dict]:
        folder = self._folder(instance, "saves")
        result = []
        try:
            dirs = sorted((p for p in folder.iterdir() if p.is_dir()),
                          key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError:
            return result
        for path in dirs:
            try:
                stamp = path.stat().st_mtime
            except OSError:
                stamp = 0
            result.append({"path": path, "name": path.name, "modified": stamp})
        return result

    def latest_log(self, instance: dict) -> Path | None:
        folder = self.game_dir(instance) / "logs"
        if not folder.is_dir():
            return None
        try:
            files = sorted(folder.glob("*.log"), key=lambda p: p.stat().st_mtime,
                           reverse=True)
        except OSError:
            return None
        return files[0] if files else None

    # Import / export ------------------------------------------------
    def export(self, instance: dict, dest: Path) -> Path:
        folder = self.game_dir(instance)
        dest = Path(dest)
        payload = {key: value for key, value in instance.items()
                   if key not in ("resolved_version",)}
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("instance.json", json.dumps(payload, indent=2,
                                                         ensure_ascii=False))
            if folder.is_dir():
                for path in folder.rglob("*"):
                    if not path.is_file():
                        continue
                    relative = path.relative_to(folder)
                    archive.write(path, f"minecraft/{relative.as_posix()}")
            icon = Path(str(instance.get("icon_path") or ""))
            if icon.is_file():
                try:
                    inside = (icon.resolve() == folder.resolve()
                              or folder.resolve() in icon.resolve().parents)
                except OSError:
                    inside = False
                if not inside:
                    try:
                        import io

                        from PIL import Image
                        with Image.open(icon) as source:
                            image = source.convert("RGBA")
                            image.thumbnail((256, 256), Image.LANCZOS)
                            buffer = io.BytesIO()
                            image.save(buffer, "PNG")
                        archive.writestr("minecraft/blockys-icon.png",
                                         buffer.getvalue())
                    except (OSError, ValueError):
                        pass
        return dest

    def import_zip(self, source: Path, name: str | None = None) -> dict:
        source = Path(source)
        instance = None
        folder = None
        try:
            with zipfile.ZipFile(source) as archive:
                names = archive.namelist()
                if "instance.json" not in names:
                    raise InstanceError("El paquete no contiene instance.json")
                try:
                    payload = json.loads(archive.read("instance.json").decode("utf-8"))
                except (ValueError, UnicodeDecodeError) as exc:
                    raise InstanceError("instance.json invalido") from exc
                if not isinstance(payload, dict) or not payload.get("version"):
                    raise InstanceError("El paquete no tiene una version valida")
                instance = _default_instance(
                    self.instances, name or payload.get("name") or source.stem,
                    str(payload.get("version")), str(payload.get("loader") or "vanilla"))
                for key in ("memory_mb", "resolution_width", "resolution_height",
                            "custom_resolution", "java_mode", "java_path",
                            "aikar_flags", "icon", "icon_path", "group", "notes",
                            "jvm_args", "game_args", "env_vars", "pre_launch",
                            "post_exit", "quick_play_type", "quick_play_target"):
                    if key in payload:
                        instance[key] = payload[key]
                instance["loader_version"] = str(payload.get("loader_version") or "")
                self.instances.append(instance)
                self.data["selected"] = instance["id"]
                self.save()
                folder = self.game_dir(instance)
                folder.mkdir(parents=True, exist_ok=True)
                for name in names:
                    if not name.startswith("minecraft/") or name.endswith("/"):
                        continue
                    relative = name[len("minecraft/"):]
                    target = (folder / relative).resolve()
                    if folder.resolve() not in target.parents:
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(name) as src, open(target, "wb") as out:
                        shutil.copyfileobj(src, out)
                self.ensure_dirs(instance)
                icon_name = Path(str(instance.get("icon_path") or "")).name
                icon_target = folder / "blockys-icon.png"
                if not icon_target.is_file() and icon_name:
                    candidate = folder / icon_name
                    if candidate.is_file():
                        icon_target = candidate
                instance["icon_path"] = (str(icon_target)
                                         if icon_target.is_file() else "")
                self.save()
                return instance
        except zipfile.BadZipFile as exc:
            self._discard_import(instance, folder)
            raise InstanceError("El archivo no es un .zip valido") from exc
        except (OSError, RuntimeError, InstanceError) as exc:
            self._discard_import(instance, folder)
            raise InstanceError(f"No se pudo importar el paquete: {exc}") from exc

    def _discard_import(self, instance: dict | None, folder: Path | None) -> None:
        if instance is None:
            return
        try:
            self.instances.remove(instance)
        except ValueError:
            pass
        if self.data.get("selected") == instance.get("id"):
            self.data["selected"] = self.instances[0]["id"] if self.instances else ""
        try:
            self.save()
        except OSError:
            pass
        if folder is not None:
            shutil.rmtree(folder, ignore_errors=True)

    def import_folder(self, source: Path, name: str, version: str,
                      loader: str = "vanilla") -> dict:
        source = Path(source)
        if not source.is_dir():
            raise InstanceError("La carpeta no existe")
        instance = self.create(name, version, loader)
        target = self.game_dir(instance)
        for item in source.iterdir():
            try:
                if item.is_dir():
                    shutil.copytree(item, target / item.name, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, target / item.name)
            except OSError:
                continue
        return instance
