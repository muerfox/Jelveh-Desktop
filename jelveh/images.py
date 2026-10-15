"""Disk and memory cache for posters and backdrops."""

from __future__ import annotations

import hashlib
import urllib.request
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QObject, QStandardPaths, Qt
from PySide6.QtGui import QImage, QPixmap

from .tasks import TaskRunner

_USER_AGENT = "JelvehDesktop/1.0"
_CACHE_LIMIT = 100 * 1024 * 1024


class ImageService(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.runner = TaskRunner(self)
        cache_root = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation) or ".")
        self.directory = cache_root / "images"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.memory: OrderedDict[str, QImage] = OrderedDict()
        self._memory_bytes = 0
        self.waiters: dict[str, list] = {}
        self._trim_disk()

    def load(self, url: str | None, callback) -> None:
        if not url:
            callback(None)
            return
        cached = self.memory.get(url)
        if cached is not None:
            self.memory.move_to_end(url)
            callback(cached)
            return
        self.waiters.setdefault(url, []).append(callback)
        if len(self.waiters[url]) > 1:
            return
        self.runner.run(lambda: self._fetch(url), lambda image, url=url: self._deliver(url, image), lambda _message, url=url: self._deliver(url, None))

    def _fetch(self, url: str) -> QImage | None:
        path = self.directory / hashlib.sha256(url.encode()).hexdigest()
        data = path.read_bytes() if path.is_file() else None
        if data is not None:
            path.touch()
        else:
            request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "image/*"})
            with urllib.request.urlopen(request, timeout=25) as response:
                data = response.read()
            if data:
                path.write_bytes(data)
                self._trim_disk()
        image = QImage()
        if not data or not image.loadFromData(data):
            path.unlink(missing_ok=True)
            return None
        return image

    def _deliver(self, url: str, image: QImage | None) -> None:
        if image is not None and not image.isNull():
            self._remember(url, image)
        else:
            image = None
        for callback in self.waiters.pop(url, []):
            callback(image)

    def _remember(self, url: str, image: QImage) -> None:
        if url in self.memory:
            self._memory_bytes -= self._image_bytes(self.memory[url])
            del self.memory[url]
        self.memory[url] = image
        self._memory_bytes += self._image_bytes(image)
        while self.memory and self._memory_bytes > _CACHE_LIMIT:
            _old, dropped = self.memory.popitem(last=False)
            self._memory_bytes -= self._image_bytes(dropped)

    def _trim_disk(self) -> None:
        files = []
        total = 0
        try:
            entries = list(self.directory.iterdir())
        except OSError:
            return
        for path in entries:
            if not path.is_file():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            files.append((stat.st_mtime, stat.st_size, path))
            total += stat.st_size
        files.sort()
        for _mtime, size, path in files:
            if total <= _CACHE_LIMIT:
                break
            try:
                path.unlink()
            except OSError:
                continue
            total -= size

    @staticmethod
    def _image_bytes(image: QImage) -> int:
        return max(int(image.sizeInBytes()), 1)


def cover_pixmap(image: QImage | None, width: int, height: int, radius: int = 0) -> QPixmap:
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.GlobalColor.transparent)
    if image is None or image.isNull() or width <= 0 or height <= 0:
        return pixmap
    scaled = image.scaled(width, height, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
    x = max(0, (scaled.width() - width) // 2)
    y = max(0, (scaled.height() - height) // 2)
    cropped = scaled.copy(x, y, width, height)
    painter_pix = QPixmap(width, height)
    painter_pix.fill(Qt.GlobalColor.transparent)
    from PySide6.QtGui import QPainter, QPainterPath

    painter = QPainter(painter_pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if radius:
        path = QPainterPath()
        path.addRoundedRect(0, 0, width, height, radius, radius)
        painter.setClipPath(path)
    painter.drawImage(0, 0, cropped)
    painter.end()
    return painter_pix
