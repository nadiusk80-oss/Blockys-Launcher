from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from . import __version__

USER_AGENT = f"Blockys/{__version__} (Minecraft Java launcher)"
CHUNK = 262144


class Cancelled(Exception):
    pass


class DownloadError(Exception):
    pass


class HttpError(Exception):
    def __init__(self, status: int, body: bytes, url: str):
        self.status = status
        self.body = body
        self.url = url
        super().__init__(f"HTTP {status} en {url}")

    @property
    def text(self) -> str:
        try:
            return self.body.decode("utf-8", "replace")
        except Exception:
            return ""

    def json(self) -> dict:
        try:
            data = json.loads(self.body or b"{}")
            return data if isinstance(data, dict) else {}
        except ValueError:
            return {}


class ConnectionError_(Exception):
    pass


@dataclass
class Task:
    url: str
    dest: Path
    sha1: str | None = None
    sha256: str | None = None
    size: int | None = None


def request(url: str, data: bytes | None = None, headers: dict | None = None,
            method: str | None = None, timeout: int = 40) -> tuple[int, bytes]:
    hdrs = {"User-Agent": USER_AGENT}
    if headers:
        hdrs.update(headers)
    req = Request(url, data=data, headers=hdrs, method=method)
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except HTTPError as exc:
        raise HttpError(exc.code, exc.read(), url) from exc
    except URLError as exc:
        raise ConnectionError_(str(exc.reason)) from exc


def http_json(url: str, data: bytes | None = None, headers: dict | None = None,
              method: str | None = None, timeout: int = 40) -> dict:
    _, body = request(url, data=data, headers=headers, method=method, timeout=timeout)
    return json.loads(body or b"{}")


class _Progress:
    def __init__(self, initial: int = 0):
        self.value = initial
        self.lock = threading.Lock()

    def add(self, n: int) -> None:
        with self.lock:
            self.value += n


def _fetch(task: Task, progress: _Progress, stop: threading.Event) -> None:
    dest = Path(task.dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    last_error: Exception | None = None
    for attempt in range(1, 5):
        if stop.is_set():
            raise Cancelled()
        written = 0
        h1 = hashlib.sha1()
        h256 = hashlib.sha256()
        try:
            req = Request(task.url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
            with urlopen(req, timeout=60) as resp, open(tmp, "wb") as out:
                while True:
                    if stop.is_set():
                        raise Cancelled()
                    chunk = resp.read(CHUNK)
                    if not chunk:
                        break
                    out.write(chunk)
                    h1.update(chunk)
                    h256.update(chunk)
                    written += len(chunk)
                    progress.add(len(chunk))
            if task.size is not None and written != task.size:
                raise OSError(f"tamano incorrecto ({written} != {task.size})")
            if task.sha1 and h1.hexdigest() != task.sha1.lower():
                raise OSError("SHA1 incorrecto")
            if task.sha256 and h256.hexdigest() != task.sha256.lower():
                raise OSError("SHA256 incorrecto")
            os.replace(tmp, dest)
            return
        except Cancelled:
            progress.add(-written)
            raise
        except Exception as exc:
            progress.add(-written)
            last_error = exc
            try:
                tmp.unlink()
            except OSError:
                pass
            if attempt < 4:
                time.sleep(0.4 * attempt)
    raise DownloadError(f"{task.url}: {last_error}")


def _hash_file(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _matches_hashes(dest: Path, task: Task) -> bool:
    try:
        if task.sha1 and _hash_file(dest, "sha1") != task.sha1.lower():
            return False
        if task.sha256 and _hash_file(dest, "sha256") != task.sha256.lower():
            return False
    except OSError:
        return False
    return True


def download_many(tasks: list[Task], workers: int = 12,
                  on_progress=None, cancel_event: threading.Event | None = None) -> None:
    unique: dict[str, Task] = {}
    for task in tasks:
        unique[str(task.dest)] = task
    pending: list[Task] = []
    known_total = 0
    for task in unique.values():
        dest = Path(task.dest)
        skip = False
        if dest.exists():
            if task.size is None:
                skip = (not (task.sha1 or task.sha256)
                        or _matches_hashes(dest, task))
            else:
                try:
                    skip = dest.stat().st_size == task.size
                except OSError:
                    skip = False
                if not skip:
                    try:
                        dest.unlink()
                    except OSError:
                        pass
        if skip:
            try:
                known_total += dest.stat().st_size
            except OSError:
                skip = False
            part = dest.with_name(dest.name + ".part")
            if part.exists():
                try:
                    part.unlink()
                except OSError:
                    pass
        if not skip:
            pending.append(task)
            known_total += task.size or 0

    progress = _Progress(known_total - sum(t.size or 0 for t in pending))
    total = known_total
    done_files = 0
    lock = threading.Lock()
    stop = threading.Event()

    def report() -> None:
        if on_progress:
            on_progress(progress.value, total, done_files, len(pending))

    report()

    def worker(task: Task) -> None:
        nonlocal done_files
        _fetch(task, progress, stop)
        with lock:
            done_files += 1
        report()

    errors: list[Exception] = []
    if pending:
        with ThreadPoolExecutor(max_workers=min(workers, len(pending))) as pool:
            futures = {pool.submit(worker, task): task for task in pending}
            for future in as_completed(futures):
                try:
                    future.result()
                except Cancelled:
                    pass
                except Exception as exc:
                    errors.append(exc)
                    stop.set()
                    for other in futures:
                        other.cancel()
                if cancel_event is not None and cancel_event.is_set():
                    stop.set()
                    for other in futures:
                        other.cancel()

    if cancel_event is not None and cancel_event.is_set():
        raise Cancelled()
    if errors:
        raise DownloadError(f"{len(errors)} descarga(s) fallaron: {errors[0]}")


def download_one(url: str, dest: Path, sha1: str | None = None,
                 sha256: str | None = None, size: int | None = None,
                 on_progress=None, cancel_event: threading.Event | None = None) -> None:
    download_many([Task(url, Path(dest), sha1=sha1, sha256=sha256, size=size)],
                  workers=1, on_progress=on_progress, cancel_event=cancel_event)
