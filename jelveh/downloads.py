"""Save streams as normal video files the app or any other player can open."""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from PySide6.QtCore import QObject, QStandardPaths, QThread, Signal

_USER_AGENT = "JelvehDesktop/1.0"


def _safe_name(text: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]+', " ", text).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:120] or "jelveh"


def format_bytes(value: int | float) -> str:
    amount = float(max(0, value))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(amount)} {unit}"
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{int(value)} B"


def format_speed(bps: float) -> str:
    if bps <= 0:
        return "—"
    return f"{format_bytes(bps)}/s"


def format_eta(seconds: float) -> str:
    if seconds <= 0 or seconds == float("inf"):
        return "—"
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_progress_size(received: int, total: int) -> str:
    """Downloaded amount, then «از», then the full size. Show this in an LTR label."""
    if total <= 0:
        return format_bytes(received)
    return f"{format_bytes(received)} از {format_bytes(total)}"


class _Job(QThread):
    progressed = Signal(str, int, int, float)
    succeeded = Signal(str, str)
    failed = Signal(str, str)
    paused = Signal(str, int, int)

    def __init__(self, item_id: str, url: str, destination: Path):
        super().__init__()
        self.item_id = item_id
        self.url = url
        self.destination = destination
        self._cancel = False
        self._pause = False

    def cancel(self) -> None:
        self._cancel = True
        self._pause = False

    def pause(self) -> None:
        self._pause = True

    def run(self) -> None:
        partial = self.destination.with_suffix(self.destination.suffix + ".part")
        try:
            partial.parent.mkdir(parents=True, exist_ok=True)
            received = partial.stat().st_size if partial.exists() else 0
            headers = {"User-Agent": _USER_AGENT}
            if received > 0:
                headers["Range"] = f"bytes={received}-"
            request = urllib.request.Request(self.url, headers=headers)
            with urllib.request.urlopen(request, timeout=60) as response:
                status = getattr(response, "status", None) or response.getcode()
                content_length = int(response.headers.get("Content-Length") or 0)
                total = 0
                if status == 206:
                    content_range = response.headers.get("Content-Range") or ""
                    if "/" in content_range:
                        try:
                            total = int(content_range.rsplit("/", 1)[-1])
                        except ValueError:
                            total = received + content_length
                    else:
                        total = received + content_length
                    mode = "ab"
                else:
                    # Server ignored Range — start the file again.
                    received = 0
                    total = content_length
                    mode = "wb"
                last_emit = 0.0
                last_bytes = received
                last_tick = time.monotonic()
                speed = 0.0
                with partial.open(mode) as handle:
                    while not self._cancel and not self._pause:
                        chunk = response.read(1024 * 256)
                        if not chunk:
                            break
                        handle.write(chunk)
                        received += len(chunk)
                        now = time.monotonic()
                        elapsed = now - last_tick
                        if elapsed >= 0.35:
                            speed = (received - last_bytes) / max(elapsed, 0.001)
                            last_bytes = received
                            last_tick = now
                        if now - last_emit >= 0.25:
                            last_emit = now
                            self.progressed.emit(self.item_id, received, total, speed)
            if self._cancel:
                partial.unlink(missing_ok=True)
                self.failed.emit(self.item_id, "لغو شد")
                return
            if self._pause:
                self.progressed.emit(self.item_id, received, total, 0.0)
                self.paused.emit(self.item_id, received, total)
                return
            if total and received < total:
                self.failed.emit(self.item_id, "دانلود ناتمام ماند")
                return
            partial.replace(self.destination)
            self.succeeded.emit(self.item_id, str(self.destination))
        except Exception as error:  # noqa: BLE001
            message = str(error) or "دانلود ناموفق بود"
            if isinstance(error, urllib.error.HTTPError) and error.code in {416, 400} and partial.exists():
                partial.unlink(missing_ok=True)
                message = "ادامه دانلود ممکن نشد؛ دوباره تلاش کنید"
            self.failed.emit(self.item_id, message)


class DownloadManager(QObject):
    updated = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        downloads = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
        home = Path.home() / "Downloads"
        self.folder = Path(downloads or home) / "Jelveh"
        self.folder.mkdir(parents=True, exist_ok=True)
        self.catalog = self.folder / "library.json"
        self.items: list[dict] = self._load()
        self._jobs: dict[str, _Job] = {}
        self._last_emit = 0.0

    def ready_path(self, url: str) -> str | None:
        for item in self.items:
            if item.get("url") == url and item.get("status") == "done":
                path = Path(item.get("path") or "")
                if path.is_file():
                    return str(path)
        return None

    def find_url(self, url: str) -> dict | None:
        return next((item for item in self.items if item.get("url") == url), None)

    def start(self, *, url: str, title: str, detail: str) -> dict:
        existing = next((item for item in self.items if item.get("url") == url), None)
        if existing and existing.get("status") == "done" and Path(existing.get("path") or "").is_file():
            self.updated.emit()
            return existing
        if existing and existing.get("status") == "downloading" and existing.get("id") in self._jobs:
            return existing
        if existing and existing.get("status") in {"paused", "error", "downloading"}:
            return self.resume(existing["id"])

        suffix = Path(url.split("?", 1)[0]).suffix or ".mkv"
        if suffix.lower() not in {".mkv", ".mp4", ".webm", ".avi", ".m4v"}:
            suffix = ".mkv"
        filename = f"{_safe_name(title)} - {_safe_name(detail)}{suffix}"
        destination = self.folder / filename
        counter = 2
        while destination.exists() or destination.with_suffix(destination.suffix + ".part").exists():
            destination = self.folder / f"{_safe_name(title)} - {_safe_name(detail)} ({counter}){suffix}"
            counter += 1
        item = {
            "id": hashlib.sha1(f"{url}:{time.time()}".encode()).hexdigest()[:12],
            "url": url,
            "title": title,
            "detail": detail,
            "path": str(destination),
            "status": "downloading",
            "received": 0,
            "total": 0,
            "speed": 0.0,
            "error": "",
        }
        self.items = [entry for entry in self.items if entry.get("url") != url]
        self.items.insert(0, item)
        self._save()
        self._launch(item)
        self.updated.emit()
        return item

    def pause(self, item_id: str) -> None:
        job = self._jobs.get(item_id)
        if job:
            job.pause()
        self._mark(item_id, status="paused", speed=0.0)

    def resume(self, item_id: str) -> dict | None:
        item = next((entry for entry in self.items if entry.get("id") == item_id), None)
        if not item:
            return None
        if item.get("status") == "done" and Path(item.get("path") or "").is_file():
            return item
        if item_id in self._jobs:
            return item
        path = Path(item.get("path") or "")
        partial = path.with_suffix(path.suffix + ".part")
        received = partial.stat().st_size if partial.exists() else int(item.get("received") or 0)
        item["received"] = received
        item["status"] = "downloading"
        item["speed"] = 0.0
        item["error"] = ""
        self._save()
        self._launch(item)
        self.updated.emit()
        return item

    def cancel(self, item_id: str) -> None:
        job = self._jobs.get(item_id)
        if job:
            job.cancel()
        item = next((entry for entry in self.items if entry.get("id") == item_id), None)
        if item:
            path = Path(item.get("path") or "")
            path.with_suffix(path.suffix + ".part").unlink(missing_ok=True)
        self._mark(item_id, status="error", error="لغو شد", speed=0.0, received=0)

    def remove(self, item_id: str) -> None:
        job = self._jobs.get(item_id)
        if job:
            job.cancel()
        kept = []
        for item in self.items:
            if item.get("id") != item_id:
                kept.append(item)
                continue
            path = Path(item.get("path") or "")
            path.with_suffix(path.suffix + ".part").unlink(missing_ok=True)
            if item.get("status") == "done":
                path.unlink(missing_ok=True)
        self.items = kept
        self._save()
        self.updated.emit()

    def _launch(self, item: dict) -> None:
        destination = Path(item["path"])
        job = _Job(item["id"], item["url"], destination)
        job.progressed.connect(self._progress)
        job.succeeded.connect(self._success)
        job.failed.connect(self._failure)
        job.paused.connect(self._paused)
        job.finished.connect(lambda item_id=item["id"]: self._jobs.pop(item_id, None))
        self._jobs[item["id"]] = job
        job.start()

    def _progress(self, item_id: str, received: int, total: int, speed: float) -> None:
        for item in self.items:
            if item.get("id") != item_id:
                continue
            item["received"] = received
            item["total"] = total
            item["speed"] = speed
            if item.get("status") != "paused":
                item["status"] = "downloading"
            break
        now = time.monotonic()
        if now - self._last_emit < 0.25:
            return
        self._last_emit = now
        self._save()
        self.updated.emit()

    def _paused(self, item_id: str, received: int, total: int) -> None:
        self._mark(item_id, status="paused", received=received, total=total, speed=0.0, error="")

    def _success(self, item_id: str, path: str) -> None:
        self._mark(item_id, status="done", path=path, error="", speed=0.0)

    def _failure(self, item_id: str, message: str) -> None:
        self._mark(item_id, status="error", error=message, speed=0.0)

    def _mark(self, item_id: str, **fields) -> None:
        for item in self.items:
            if item.get("id") == item_id:
                item.update(fields)
                break
        self._save()
        self.updated.emit()

    def _load(self) -> list[dict]:
        if not self.catalog.exists():
            return []
        try:
            data = json.loads(self.catalog.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        items = data if isinstance(data, list) else []
        for item in items:
            path = Path(item.get("path") or "")
            partial = path.with_suffix(path.suffix + ".part")
            if item.get("status") == "downloading":
                if partial.exists():
                    item["status"] = "paused"
                    item["received"] = partial.stat().st_size
                    item["error"] = ""
                else:
                    item["status"] = "error"
                    item["error"] = "دانلود ناتمام ماند"
            item.setdefault("speed", 0.0)
            item.setdefault("received", 0)
            item.setdefault("total", 0)
        return items

    def _save(self) -> None:
        self.catalog.write_text(json.dumps(self.items, ensure_ascii=False, indent=2), encoding="utf-8")
