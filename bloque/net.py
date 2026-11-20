from __future__ import annotations

import hashlib
import json
import os
import random
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
    def __init__(self, total: int = 0, value: int = 0):
        self.value = value
        self.total = total
        self.lock = threading.Lock()

    def add(self, n: int) -> None:
        with self.lock:
            self.value += n

    def grow(self, n: int) -> None:
        with self.lock:
            self.total += n

    def rollback(self, value: int, total: int = 0) -> None:
        with self.lock:
            self.value -= value
            self.total -= total


class _BadPayload(DownloadError):
    pass


def _remove(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def _fetch(task: Task, progress: _Progress, stop: threading.Event,
           on_tick=None, cancel_event: threading.Event | None = None) -> None:
    dest = Path(task.dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    grow = task.size is None
    last_error: Exception | None = None
    for attempt in range(1, 6):
        if stop.is_set():
            raise Cancelled()
        if attempt > 1:
            time.sleep(min(4.0, 0.6 * attempt) + random.uniform(0.0, 0.5))

        offset = 0
        try:
            if tmp.is_file():
                offset = tmp.stat().st_size
        except OSError:
            offset = 0
        if task.size is not None:
            if offset > task.size:
                _remove(tmp)
                offset = 0
            elif offset == task.size and offset > 0:
                if _matches_hashes(tmp, task):
                    os.replace(tmp, dest)
                    progress.add(offset)
                    if on_tick:
                        on_tick()
                    return
                _remove(tmp)
                offset = 0
        elif offset:
            _remove(tmp)
            offset = 0

        h1 = hashlib.sha1()
        h256 = hashlib.sha256()
        if offset:
            try:
                with open(tmp, "rb") as handle:
                    for chunk in iter(lambda: handle.read(CHUNK), b""):
                        h1.update(chunk)
                        h256.update(chunk)
            except OSError:
                _remove(tmp)
                offset = 0
                h1 = hashlib.sha1()
                h256 = hashlib.sha256()
            else:
                progress.add(offset)

        written = offset
        grown = offset if grow else 0
        headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        resp = None
        try:
            resp = urlopen(Request(task.url, headers=headers), timeout=60)
            if offset and getattr(resp, "status", 200) != 206:
                out = open(tmp, "wb")
                progress.rollback(offset)
                written = 0
                if grow:
                    progress.grow(-offset)
                    grown = 0
                h1 = hashlib.sha1()
                h256 = hashlib.sha256()
            else:
                out = open(tmp, "ab" if offset else "wb")
            try:
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
                    if grow:
                        progress.grow(len(chunk))
                        grown += len(chunk)
                    if on_tick:
                        on_tick()
            finally:
                out.close()
            if task.size is not None and written != task.size:
                if written < task.size:
                    raise OSError(f"descarga incompleta ({written} de {task.size})")
                raise _BadPayload(f"tamano incorrecto ({written} != {task.size})")
            if task.sha1 and h1.hexdigest() != task.sha1.lower():
                raise _BadPayload("SHA1 incorrecto")
            if task.sha256 and h256.hexdigest() != task.sha256.lower():
                raise _BadPayload("SHA256 incorrecto")
            os.replace(tmp, dest)
            return
        except Cancelled:
            progress.rollback(written, grown)
            if cancel_event is not None and cancel_event.is_set():
                _remove(tmp)
            raise
        except HTTPError as exc:
            progress.rollback(written, grown)
            last_error = DownloadError(f"HTTP {exc.code} en {task.url}")
            if exc.code == 416 and offset:
                _remove(tmp)
                continue
            if exc.code in (408, 425, 429) or exc.code >= 500:
                continue
            _remove(tmp)
            raise last_error from exc
        except _BadPayload as exc:
            progress.rollback(written, grown)
            _remove(tmp)
            last_error = exc
            continue
        except Exception as exc:
            progress.rollback(written, grown)
            last_error = exc
            continue
        finally:
            if resp is not None:
                try:
                    resp.close()
                except OSError:
                    pass
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
    skipped_bytes = 0
    for task in unique.values():
        dest = Path(task.dest)
        skip = False
        if dest.exists():
            if task.size is None:
                skip = (not (task.sha1 or task.sha256)
                        or _matches_hashes(dest, task))
            else:
                try:
                    size_ok = dest.stat().st_size == task.size
                except OSError:
                    size_ok = False
                skip = size_ok and _matches_hashes(dest, task)
                if not skip:
                    try:
                        dest.unlink()
                    except OSError:
                        pass
        if skip:
            try:
                size = dest.stat().st_size
            except OSError:
                skip = False
            else:
                skipped_bytes += size
                known_total += size
            _remove(dest.with_name(dest.name + ".part"))
        if not skip:
            pending.append(task)
            known_total += task.size or 0

    progress = _Progress(known_total, skipped_bytes)
    done_files = 0
    lock = threading.Lock()
    stop = threading.Event()
    last_report = [0.0]

    def report(force: bool = False) -> None:
        if cancel_event is not None and cancel_event.is_set():
            stop.set()
        if on_progress is None:
            return
        now = time.monotonic()
        with lock:
            if not force and now - last_report[0] < 0.15:
                return
            last_report[0] = now
            done = done_files
        on_progress(progress.value, progress.total, done, len(pending))

    report(force=True)

    def worker(task: Task) -> None:
        nonlocal done_files
        _fetch(task, progress, stop, on_tick=report, cancel_event=cancel_event)
        with lock:
            done_files += 1
        report(force=True)

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
