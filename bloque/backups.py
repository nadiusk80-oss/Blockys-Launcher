from __future__ import annotations

import os
import re
import time
import zipfile
from pathlib import Path, PurePosixPath

from .util import safe_extract

BACKUP_FOLDER = "backups"
DEFAULT_KEEP = 5

_ENTRY = re.compile(r"^(?P<world>.+)-(?P<stamp>\d{8}-\d{6})(?:-\d+)?\.zip$")
_OLD_WORLD = re.compile(r"\.old-\d{8}-\d{6}(?:-\d+)?$")


class BackupError(Exception):
    pass


def folder(game_dir: Path) -> Path:
    return Path(game_dir) / BACKUP_FOLDER


def _stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def worlds(game_dir: Path) -> list[Path]:
    saves = Path(game_dir) / "saves"
    try:
        items = (p for p in saves.iterdir()
                 if p.is_dir() and not _OLD_WORLD.search(p.name))
    except OSError:
        return []
    return sorted(items, key=lambda p: p.name.lower())


def create(world: Path, game_dir: Path, on_status=None,
           cancel_event=None) -> Path:
    world = Path(world)
    if not world.is_dir():
        raise BackupError(f"El mundo {world.name} no existe")
    dest = folder(game_dir)
    try:
        dest.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise BackupError(f"No se pudo crear la carpeta de copias: {exc}") from exc
    target = dest / f"{world.name}-{_stamp()}.zip"
    counter = 2
    while target.exists():
        target = dest / f"{world.name}-{_stamp()}-{counter}.zip"
        counter += 1
    part = target.with_name(target.name + ".part")
    if on_status:
        on_status(f"Respaldando {world.name}...")
    try:
        with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in sorted(world.rglob("*")):
                if cancel_event is not None and cancel_event.is_set():
                    raise BackupError("Copia cancelada")
                if not item.is_file():
                    continue
                archive.write(
                    item,
                    (PurePosixPath(world.name) / item.relative_to(world).as_posix()).as_posix())
        os.replace(part, target)
    except BackupError:
        _remove(part)
        raise
    except (OSError, zipfile.BadZipFile) as exc:
        _remove(part)
        raise BackupError(f"No se pudo respaldar {world.name}: {exc}") from exc
    return target


def _member_ok(name: str) -> bool:
    if name.startswith(("/", "\\")) or (len(name) > 1 and name[1] == ":"):
        return False
    parts = [part for part in PurePosixPath(name).parts if part not in ("", ".")]
    return bool(parts) and all(part != ".." for part in parts)


def restore(archive: Path, game_dir: Path, on_status=None) -> Path:
    archive = Path(archive)
    try:
        with zipfile.ZipFile(archive) as zf:
            names = [info.filename for info in zf.infolist()]
            if not names or not all(_member_ok(name) for name in names):
                raise BackupError("La copia tiene rutas no válidas")
            roots = {PurePosixPath(name).parts[0] for name in names
                     if not PurePosixPath(name).parts[0] in ("", ".")}
            if len(roots) != 1:
                raise BackupError("La copia debe contener un solo mundo")
            name = next(iter(roots))
            saves = Path(game_dir) / "saves"
            saves.mkdir(parents=True, exist_ok=True)
            target = saves / name
            if target.exists():
                stamp = _stamp()
                old = saves / f"{name}.old-{stamp}"
                counter = 2
                while old.exists():
                    old = saves / f"{name}.old-{stamp}-{counter}"
                    counter += 1
                target.rename(old)
            if on_status:
                on_status(f"Restaurando {name}...")
            safe_extract(archive, saves)
    except zipfile.BadZipFile as exc:
        raise BackupError("El archivo elegido no es una copia válida") from exc
    except OSError as exc:
        raise BackupError(f"No se pudo restaurar: {exc}") from exc
    return target


def entries(game_dir: Path) -> list[dict]:
    dest = folder(game_dir)
    try:
        files = [p for p in dest.iterdir()
                 if p.is_file() and p.suffix.lower() == ".zip"]
    except OSError:
        return []
    result = []
    for path in files:
        match = _ENTRY.match(path.name)
        try:
            stat = path.stat()
        except OSError:
            continue
        result.append({
            "path": path,
            "world": match.group("world") if match else path.stem,
            "stamp": match.group("stamp") if match else "",
            "size": stat.st_size,
            "modified": stat.st_mtime,
        })
    result.sort(key=lambda item: (item["modified"], item["path"].name),
                reverse=True)
    return result


def prune(game_dir: Path, keep: int = DEFAULT_KEEP) -> int:
    keep = max(1, min(50, int(keep)))
    grouped: dict[str, list[dict]] = {}
    for entry in entries(game_dir):
        grouped.setdefault(entry["world"], []).append(entry)
    removed = 0
    for items in grouped.values():
        items.sort(key=lambda item: (item["modified"], item["path"].name),
                   reverse=True)
        for entry in items[keep:]:
            try:
                entry["path"].unlink()
                removed += 1
            except OSError:
                pass
    return removed


def auto_backup(game_dir: Path, keep: int = DEFAULT_KEEP, on_status=None,
                cancel_event=None) -> int:
    count = 0
    for world in worlds(game_dir):
        if cancel_event is not None and cancel_event.is_set():
            break
        try:
            create(world, game_dir, on_status=on_status,
                   cancel_event=cancel_event)
            count += 1
        except BackupError as exc:
            if on_status:
                on_status(f"Sin respaldo de {world.name}: {exc}")
    if count:
        prune(game_dir, keep)
    return count


def _remove(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass
