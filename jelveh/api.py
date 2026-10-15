"""HTTP client for the Jelveh API at panel.jelveh.top."""

from __future__ import annotations

import json
import platform
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

API_ROOT = "https://panel.jelveh.top/api/v1"
SITE_ORIGIN = "https://jelveh.top"
DEVICE_NAME = f"jelveh-desktop-{platform.system().lower() or 'unknown'}"

_PROXY_HOST = re.compile(
    r"^(?:dls\d+\.varzeshha3-uploader\.top|(?:[\w-]+\.)?jelveh\.top)$",
    re.IGNORECASE,
)

_MESSAGES = {
    "The phone has already been taken.": "این شماره قبلاً ثبت شده است.",
    "These credentials do not match our records.": "شماره یا رمز عبور نادرست است.",
    "Too Many Attempts.": "تعداد تلاش‌ها زیاد است. کمی بعد دوباره امتحان کنید.",
}


class ApiError(Exception):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


def media_url(url: str | None) -> str:
    """Rewrite file hosts through the same media proxy the website uses."""
    if not url:
        return ""
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or ""
    if parsed.scheme not in ("http", "https") or not _PROXY_HOST.match(host):
        return url
    path = parsed.path.lstrip("/")
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{SITE_ORIGIN}/media-proxy/{parsed.scheme}/{host}/{path}{query}"


def normalize_links(raw: list[dict] | None) -> list[dict]:
    links = []
    for item in raw or []:
        url = item.get("url") or ""
        quality = (item.get("quality") or {}).get("name") or ""
        if url and quality:
            links.append(
                {
                    "url": url,
                    "play_url": media_url(url),
                    "quality": quality,
                    "type": item.get("type") or "other",
                }
            )
    return links


def preferred_link_index(links: list[dict]) -> int:
    """Match the website: mp4 first, then 480p, then 720p."""
    if not links:
        return 0
    for index, link in enumerate(links):
        if re.search(r"\.mp4($|\?)", link["url"], re.IGNORECASE):
            return index
    for needle in ("480p", "720p"):
        for index, link in enumerate(links):
            haystack = f"{link['quality']} {link['url']}"
            if re.search(needle, haystack, re.IGNORECASE):
                return index
    return 0


def link_label(link: dict) -> str:
    kind = {"dubbed": "دوبله", "subbed": "زیرنویس"}.get(link.get("type") or "", "سایر")
    return f"{link.get('quality') or 'کیفیت'} · {kind}"


class JelvehApi:
    def __init__(self, token: str | None = None):
        self.token = token or None

    def home(self) -> list[dict]:
        return self._data("GET", "/home")

    def movies(self, **params: Any) -> tuple[list[dict], dict]:
        return self._page("GET", "/movies", params)

    def series(self, **params: Any) -> tuple[list[dict], dict]:
        return self._page("GET", "/series", params)

    def movie(self, movie_id: int | str) -> dict:
        return self._data("GET", f"/movies/{movie_id}")

    def series_detail(self, series_id: int | str) -> dict:
        return self._data("GET", f"/series/{series_id}")

    def seasons(self, series_id: int | str) -> list[dict]:
        return self._data("GET", f"/series/{series_id}/seasons") or []

    def episodes(self, season_id: int) -> list[dict]:
        return self._data("GET", f"/seasons/{season_id}/episodes", {"per_page": 100}) or []

    def episode(self, episode_id: int) -> dict:
        return self._data("GET", f"/episodes/{episode_id}")

    def search(self, text: str, page: int = 1) -> tuple[list[dict], dict]:
        return self._page("GET", "/search", {"search": text, "page": page, "per_page": 24})

    def genres(self) -> list[dict]:
        data, _meta = self._page("GET", "/genres", {"per_page": 100, "sort": "name", "direction": "asc"})
        return data

    def comments(self, kind: str, title_id: int, page: int = 1) -> tuple[list[dict], dict]:
        path = f"/{'movies' if kind == 'movie' else 'series'}/{title_id}/comments"
        return self._page("GET", path, {"page": page, "per_page": 20, "direction": "desc"})

    def post_comment(self, kind: str, title_id: int, body: str, spoil: bool = False) -> dict:
        path = f"/{'movies' if kind == 'movie' else 'series'}/{title_id}/comments"
        return self._data("POST", path, form={"body": body, "spoil": spoil})

    def react(self, kind: str, title_id: int, reaction: str) -> dict:
        return self._data("POST", "/reactions", form={"type": kind, "id": title_id, "reaction": reaction})

    def clear_reaction(self, kind: str, title_id: int) -> dict:
        return self._data("DELETE", "/reactions", form={"type": kind, "id": title_id})

    def favorites(self, page: int = 1) -> tuple[list[dict], dict]:
        return self._page("GET", "/favorites", {"page": page, "per_page": 40, "direction": "desc"})

    def add_favorite(self, kind: str, title_id: int) -> dict:
        return self._data("POST", "/favorites", form={"type": kind, "id": title_id})

    def remove_favorite(self, favorite_id: int) -> dict:
        return self._data("DELETE", f"/favorites/{favorite_id}")

    def playlists(self) -> list[dict]:
        data, _meta = self._page("GET", "/playlists", {"per_page": 100})
        return data

    def playlist(self, playlist_id: int) -> dict:
        return self._data("GET", f"/playlists/{playlist_id}")

    def create_playlist(self, name: str, description: str = "") -> dict:
        return self._data("POST", "/playlists", form={"name": name, "description": description or None})

    def delete_playlist(self, playlist_id: int) -> dict:
        return self._data("DELETE", f"/playlists/{playlist_id}")

    def add_playlist_item(self, playlist_id: int, kind: str, title_id: int) -> dict:
        return self._data(
            "POST",
            f"/playlists/{playlist_id}/items",
            form={"type": kind, "id": title_id},
        )

    def remove_playlist_item(self, playlist_id: int, item_id: int) -> dict:
        return self._data("DELETE", f"/playlists/{playlist_id}/items/{item_id}")

    def login_phone(self, phone: str, password: str) -> dict:
        return self._data(
            "POST",
            "/auth/login/phone",
            form={"phone": phone, "password": password, "device_name": DEVICE_NAME},
        )

    def register(self, phone: str, password: str, name: str = "") -> dict:
        return self._data(
            "POST",
            "/auth/register",
            form={
                "phone": phone,
                "password": password,
                "password_confirmation": password,
                "name": name or None,
                "device_name": DEVICE_NAME,
            },
        )

    def me(self) -> dict:
        return self._data("GET", "/auth/me")

    def logout(self) -> None:
        try:
            self._data("POST", "/auth/logout")
        except ApiError:
            pass
        self.token = None

    def _page(self, method: str, path: str, params: dict | None = None) -> tuple[list, dict]:
        body = self._request(method, path, params=params)
        data = body.get("data") or []
        return data, body.get("meta") or {}

    def _data(self, method: str, path: str, params: dict | None = None, form: dict | None = None):
        body = self._request(method, path, params=params, form=form)
        return body.get("data")

    def _request(self, method: str, path: str, params: dict | None = None, form: dict | None = None) -> dict:
        query = ""
        if params:
            clean = {key: value for key, value in params.items() if value not in (None, "")}
            if clean:
                query = "?" + urllib.parse.urlencode(clean)
        url = API_ROOT + path + query
        payload = _encode_form(form) if form is not None else None
        request = urllib.request.Request(url, data=payload, method=method)
        request.add_header("Accept", "application/json")
        request.add_header("User-Agent", f"JelvehDesktop/1.0 ({DEVICE_NAME})")
        if payload is not None:
            request.add_header("Content-Type", "application/x-www-form-urlencoded")
        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read().decode("utf-8")
                status = response.status
        except urllib.error.HTTPError as error:
            raw = error.read().decode("utf-8", "replace")
            status = error.code
        except urllib.error.URLError as error:
            raise ApiError("اتصال به سرور جلوه برقرار نشد.") from error
        except TimeoutError as error:
            raise ApiError("پاسخ سرور جلوه طول کشید. دوباره تلاش کنید.") from error

        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError as error:
            raise ApiError("پاسخ سرور قابل خواندن نبود.", status) from error
        if status >= 400 or body.get("success") is False:
            raise ApiError(_error_message(body, status), status)
        return body


def _encode_form(fields: dict) -> bytes:
    clean: dict[str, str] = {}
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, bool):
            clean[key] = "1" if value else "0"
        else:
            clean[key] = str(value)
    return urllib.parse.urlencode(clean).encode()


def _error_message(body: dict, status: int) -> str:
    errors = body.get("errors") or {}
    if isinstance(errors, dict) and errors:
        parts = []
        for messages in errors.values():
            if isinstance(messages, list) and messages:
                parts.append(_translate(str(messages[0])))
            elif isinstance(messages, str):
                parts.append(_translate(messages))
        if parts:
            return " ".join(parts)
    message = body.get("message")
    if message:
        return _translate(str(message))
    if status == 401:
        return "برای این کار باید وارد حساب شوید."
    if status == 404:
        return "این مورد پیدا نشد."
    if status == 429:
        return "تعداد درخواست‌ها زیاد است. کمی بعد دوباره امتحان کنید."
    return "درخواست انجام نشد."


def _translate(message: str) -> str:
    return _MESSAGES.get(message, message)
