"""Saved login, theme, and continue-watching history."""

from __future__ import annotations

import json
import time

from PySide6.QtCore import QObject, QSettings, Signal

from .api import JelvehApi
from .images import ImageService
from .tasks import TaskRunner
from .theme import Theme


class Session(QObject):
    auth_changed = Signal()
    history_changed = Signal()

    def __init__(self):
        super().__init__()
        self.settings = QSettings("jelveh.top", "Jelveh")
        self.theme = Theme(str(self.settings.value("ui/theme", "dark")))
        token = self.settings.value("auth/token", "")
        self.api = JelvehApi(str(token) if token else None)
        self.images = ImageService(self)
        self.tasks = TaskRunner(self)
        self.user = None
        self.favorites: dict[tuple, int] = {}
        self.theme.changed.connect(self._store_theme)

    def set_session(self, payload: dict | None) -> None:
        if not payload:
            self.api.token = None
            self.user = None
            self.favorites = {}
            self.settings.remove("auth/token")
            self.settings.remove("auth/user")
            self.auth_changed.emit()
            return
        self.user = payload.get("user") or payload
        token = payload.get("token")
        if token:
            self.api.token = token
            self.settings.setValue("auth/token", token)
        self.settings.setValue("auth/user", json.dumps(self.user, ensure_ascii=False))
        self.auth_changed.emit()

    def logout(self) -> None:
        token = self.api.token
        self.set_session(None)
        if token:
            self.api.token = token
            self.tasks.run(self.api.logout, lambda _result: None, lambda _message: None)
            self.api.token = None

    def restore_user(self) -> None:
        raw = self.settings.value("auth/user", "")
        if raw:
            try:
                self.user = json.loads(str(raw))
            except json.JSONDecodeError:
                self.user = None

    def remember(self, entry: dict) -> None:
        history = self.history()
        key = (entry.get("type"), entry.get("id"), entry.get("episode_id"))
        history = [item for item in history if (item.get("type"), item.get("id"), item.get("episode_id")) != key]
        ratio = entry["position"] / entry["duration"] if entry.get("duration") else 0
        if 0.02 < ratio < 0.92:
            entry["updated"] = int(time.time())
            history.insert(0, entry)
        self.settings.setValue("playback/history", json.dumps(history[:24], ensure_ascii=False))
        self.history_changed.emit()

    def history(self) -> list[dict]:
        raw = self.settings.value("playback/history", "")
        if not raw:
            return []
        try:
            data = json.loads(str(raw))
        except json.JSONDecodeError:
            return []
        return data if isinstance(data, list) else []

    def volume(self) -> int:
        try:
            return int(self.settings.value("playback/volume", 80))
        except (TypeError, ValueError):
            return 80

    def set_volume(self, value: int) -> None:
        self.settings.setValue("playback/volume", int(value))

    def _store_theme(self) -> None:
        self.settings.setValue("ui/theme", self.theme.mode)
