from __future__ import annotations

import gzip
import json
import os
import shutil
import socket
import struct
import time
import zlib
from pathlib import Path


BYTE_KEYS = {"hidden", "acceptTextures"}
STATUS_PROTOCOL = 767


class ServerError(Exception):
    pass


class _Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def take(self, count: int) -> bytes:
        if count < 0:
            raise ServerError("La lista de servidores está dañada")
        end = self.pos + count
        if end > len(self.data):
            raise ServerError("La lista de servidores está incompleta")
        chunk = self.data[self.pos:end]
        self.pos = end
        return chunk

    def u1(self) -> int:
        return self.take(1)[0]

    def i2(self) -> int:
        return struct.unpack(">h", self.take(2))[0]

    def u2(self) -> int:
        return struct.unpack(">H", self.take(2))[0]

    def i4(self) -> int:
        return struct.unpack(">i", self.take(4))[0]

    def i8(self) -> int:
        return struct.unpack(">q", self.take(8))[0]

    def f4(self) -> float:
        return struct.unpack(">f", self.take(4))[0]

    def f8(self) -> float:
        return struct.unpack(">d", self.take(8))[0]

    def string(self) -> str:
        length = self.u2()
        return self.take(length).decode("utf-8", "replace")

    def payload(self, tag: int, depth: int = 0):
        if depth > 64:
            raise ServerError("La lista de servidores está dañada")
        if tag == 1:
            return struct.unpack(">b", self.take(1))[0]
        if tag == 2:
            return self.i2()
        if tag == 3:
            return self.i4()
        if tag == 4:
            return self.i8()
        if tag == 5:
            return self.f4()
        if tag == 6:
            return self.f8()
        if tag == 7:
            return list(self.take(self.i4()))
        if tag == 8:
            return self.string()
        if tag == 9:
            child = self.u1()
            count = self.i4()
            return [self.payload(child, depth + 1) for _ in range(max(0, count))]
        if tag == 10:
            compound = {}
            while True:
                child = self.u1()
                if child == 0:
                    return compound
                name = self.string()
                compound[name] = self.payload(child, depth + 1)
        if tag == 11:
            count = self.i4()
            return [self.i4() for _ in range(max(0, count))]
        if tag == 12:
            count = self.i4()
            return [self.i8() for _ in range(max(0, count))]
        raise ServerError(f"Etiqueta NBT desconocida: {tag}")


def _write_string(value: str) -> bytes:
    raw = value.encode("utf-8")
    return struct.pack(">H", len(raw)) + raw


def _write_payload(value, tag: int | None = None) -> bytes:
    if tag is None:
        if isinstance(value, bool):
            tag = 1
        elif isinstance(value, int):
            tag = 3 if not -2**31 <= value < 2**31 else 4
        elif isinstance(value, float):
            tag = 6
        elif isinstance(value, str):
            tag = 8
        elif isinstance(value, list):
            tag = 9
        elif isinstance(value, dict):
            tag = 10
        else:
            raise ServerError("Valor NBT no compatible")
    if tag == 1:
        return struct.pack(">b", 1 if value else 0)
    if tag == 3:
        return struct.pack(">i", int(value))
    if tag == 4:
        return struct.pack(">q", int(value))
    if tag == 6:
        return struct.pack(">d", float(value))
    if tag == 8:
        return _write_string(str(value))
    if tag == 9:
        items = list(value)
        if not items:
            return struct.pack(">Bi", 8, 0)
        first = items[0]
        if isinstance(first, dict):
            child = 10
        elif isinstance(first, str):
            child = 8
        elif isinstance(first, bool) or isinstance(first, int):
            child = 3
        elif isinstance(first, float):
            child = 6
        else:
            child = 8
        body = b"".join(_write_payload(item, child) for item in items)
        return struct.pack(">Bi", child, len(items)) + body
    if tag == 10:
        body = b""
        for name, item in value.items():
            key = str(name)
            child = 1 if key in BYTE_KEYS else _tag_for(item)
            body += bytes([child]) + _write_string(key) + _write_payload(item, child)
        return body + b"\x00"
    if tag == 11:
        items = list(value)
        return struct.pack(">i", len(items)) + b"".join(
            struct.pack(">i", int(item)) for item in items)
    raise ServerError("Tipo NBT no soportado al escribir")


def _tag_for(value) -> int:
    if isinstance(value, bool):
        return 1
    if isinstance(value, int):
        return 3 if -2**31 <= value < 2**31 else 4
    if isinstance(value, float):
        return 6
    if isinstance(value, str):
        return 8
    if isinstance(value, list):
        return 9
    if isinstance(value, dict):
        return 10
    raise ServerError("Tipo NBT no soportado")


def _read_root(data: bytes) -> dict:
    reader = _Reader(data)
    root_tag = reader.u1()
    if root_tag != 10:
        raise ServerError("El archivo no es una lista de servidores de Minecraft")
    reader.string()
    root = reader.payload(10)
    return root if isinstance(root, dict) else {}


def _load_file(path: Path) -> dict:
    path = Path(path)
    if not path.is_file():
        return {"servers": []}
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ServerError(f"No se pudo leer la lista de servidores: {exc}") from exc
    if not raw:
        return {"servers": []}
    if raw[:2] == b"\x1f\x8b":
        try:
            raw = gzip.decompress(raw)
        except (OSError, EOFError, zlib.error) as exc:
            raise ServerError("La lista de servidores está dañada") from exc
    try:
        root = _read_root(raw)
    except (struct.error, IndexError, EOFError, RecursionError) as exc:
        raise ServerError("La lista de servidores está dañada") from exc
    entries = root.get("servers")
    if not isinstance(entries, list):
        root["servers"] = []
    return root


def _backup_path(path: Path) -> Path:
    return Path(path).with_name(Path(path).name + ".bak")


def _load(path: Path) -> dict:
    path = Path(path)
    try:
        return _load_file(path)
    except ServerError:
        backup = _backup_path(path)
        if backup.is_file():
            try:
                return _load_file(backup)
            except ServerError:
                pass
        raise


def _write_backup(path: Path) -> None:
    backup = _backup_path(path)
    tmp = backup.with_name(backup.name + ".part")
    try:
        with open(path, "rb") as src, open(tmp, "wb") as out:
            shutil.copyfileobj(src, out)
        os.replace(tmp, backup)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass


def _save(path: Path, root: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = b"\x0a" + _write_string("") + _write_payload(root, 10)
    tmp = path.with_name(path.name + ".part")
    try:
        if path.is_file():
            try:
                _load_file(path)
            except ServerError:
                pass
            else:
                _write_backup(path)
        tmp.write_bytes(gzip.compress(body, mtime=0))
        tmp.replace(path)
    except OSError as exc:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise ServerError(f"No se pudo guardar la lista de servidores: {exc}") from exc


def list_servers(path: Path) -> list[dict]:
    root = _load(path)
    result = []
    for entry in root.get("servers") or []:
        if not isinstance(entry, dict):
            continue
        result.append({"name": str(entry.get("name") or ""),
                       "ip": str(entry.get("ip") or "")})
    return result


def add_server(path: Path, name: str, ip: str) -> None:
    name = " ".join(str(name or "").split())[:64]
    ip = str(ip or "").strip()[:190]
    if not name or not ip:
        raise ServerError("El nombre y la dirección son obligatorios")
    root = _load(path)
    root.setdefault("servers", [])
    root["servers"].append({"name": name, "ip": ip})
    _save(path, root)


def update_server(path: Path, index: int, name: str, ip: str) -> None:
    name = " ".join(str(name or "").split())[:64]
    ip = str(ip or "").strip()[:190]
    if not name or not ip:
        raise ServerError("El nombre y la dirección son obligatorios")
    root = _load(path)
    entries = root.get("servers") or []
    if not 0 <= index < len(entries):
        raise ServerError("Ese servidor ya no existe")
    entries[index]["name"] = name
    entries[index]["ip"] = ip
    _save(path, root)


def remove_server(path: Path, index: int) -> None:
    root = _load(path)
    entries = root.get("servers") or []
    if not 0 <= index < len(entries):
        raise ServerError("Ese servidor ya no existe")
    entries.pop(index)
    _save(path, root)


def servers_file(game_dir: Path) -> Path:
    return Path(game_dir) / "servers.dat"


def split_address(address: str) -> tuple[str, int]:
    text = str(address or "").strip()
    if "://" in text:
        text = text.split("://", 1)[1]
    text = text.split("/", 1)[0].strip()
    if not text:
        raise ServerError("La dirección del servidor está vacía")
    port = 25565
    if text.startswith("["):
        end = text.find("]")
        if end < 0:
            raise ServerError("La dirección IPv6 no es válida")
        host = text[1:end]
        rest = text[end + 1:]
        if rest.startswith(":"):
            port_text = rest[1:]
            if not port_text.isdigit():
                raise ServerError("El puerto del servidor no es válido")
            port = int(port_text)
    elif text.count(":") == 1:
        host, port_text = text.rsplit(":", 1)
        if not port_text.isdigit():
            raise ServerError("El puerto del servidor no es válido")
        port = int(port_text)
    else:
        host = text
    if not host:
        raise ServerError("La dirección del servidor está vacía")
    if not 1 <= port <= 65535:
        raise ServerError("El puerto debe estar entre 1 y 65535")
    return host, port


def _encode_varint(value: int) -> bytes:
    value &= 0xFFFFFFFF
    result = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            result.append(byte | 0x80)
        else:
            result.append(byte)
            return bytes(result)


def _read_varint(read) -> int:
    result = 0
    shift = 0
    while shift <= 35:
        raw = read(1)
        if not raw:
            raise ServerError("El servidor cerró la conexión")
        byte = raw[0]
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result
        shift += 7
    raise ServerError("El servidor envió una respuesta inválida")


def _write_varint_string(value: str) -> bytes:
    raw = value.encode("utf-8")
    return _encode_varint(len(raw)) + raw


def _status_text(description) -> str:
    if isinstance(description, str):
        text = description
    elif isinstance(description, dict):
        parts = []
        if isinstance(description.get("text"), str):
            parts.append(description["text"])
        extra = description.get("extra")
        if isinstance(extra, list):
            for part in extra:
                parts.append(_status_text(part))
        text = "".join(parts)
    elif isinstance(description, list):
        text = "".join(_status_text(part) for part in description)
    else:
        text = ""
    text = text.replace("\n", " ")
    return " ".join(text.split())


def _as_int(value) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def ping(address: str, timeout: float = 3.5) -> dict:
    host, port = split_address(address)
    started = time.perf_counter()
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
    except socket.gaierror as exc:
        raise ServerError("No se pudo resolver el nombre del servidor") from exc
    except socket.timeout as exc:
        raise ServerError("El servidor no respondió a tiempo") from exc
    except OSError as exc:
        raise ServerError(f"No se pudo conectar: {exc}") from exc
    try:
        sock.settimeout(timeout)
        stream = sock.makefile("rb")
        handshake = (_encode_varint(0) + _encode_varint(STATUS_PROTOCOL)
                     + _write_varint_string(host) + struct.pack(">H", port)
                     + _encode_varint(1))
        sock.sendall(_encode_varint(len(handshake)) + handshake)
        sock.sendall(b"\x01\x00")
        length = _read_varint(stream.read)
        if length <= 0 or length > 2 * 1024 * 1024:
            raise ServerError("El servidor envió una respuesta inválida")
        packet = stream.read(length)
        if len(packet) != length:
            raise ServerError("La respuesta del servidor está incompleta")
        offset = [0]

        def read(count: int) -> bytes:
            chunk = packet[offset[0]:offset[0] + count]
            offset[0] += len(chunk)
            return chunk

        if _read_varint(read) != 0:
            raise ServerError("El servidor no devolvió estado")
        size = _read_varint(read)
        if size < 0 or size > len(packet):
            raise ServerError("La respuesta del servidor está incompleta")
        payload = read(size).decode("utf-8", "replace")
        data = json.loads(payload)
        if not isinstance(data, dict):
            raise ServerError("El servidor devolvió un estado inválido")
    except (OSError, ValueError) as exc:
        raise ServerError(f"Respuesta del servidor inválida: {exc}") from exc
    finally:
        try:
            sock.close()
        except OSError:
            pass

    version = data.get("version") if isinstance(data.get("version"), dict) else {}
    players = data.get("players") if isinstance(data.get("players"), dict) else {}
    latency = int((time.perf_counter() - started) * 1000)
    return {
        "version": str(version.get("name") or ""),
        "online": _as_int(players.get("online")),
        "max": _as_int(players.get("max")),
        "motd": _status_text(data.get("description"))[:120],
        "latency": latency,
    }
