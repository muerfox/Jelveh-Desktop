"""Main window: sidebar, pages, and the player layer."""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_MEDIA_BACKEND", "ffmpeg")

from PySide6.QtCore import QEasingCurve, QObject, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .pages import AccountPage, BrowsePage, DetailPage, HomePage, LibraryPage, SearchPage
from .player import PlayerPage
from .session import Session
from .theme import app_font, app_icon, load_fonts, logo_pixmap, stylesheet
from .widgets import Toast


class Hub(QObject):
    toast = Signal(str)
    open_title = Signal(str, int)
    play_title = Signal(str, int)
    play_detail = Signal(object, object, object)
    browse = Signal(str, str)
    resume = Signal(object)
    navigate = Signal(str)
    logged_in = Signal()


class MainWindow(QMainWindow):
    def __init__(self, session: Session, screenshot: str | None = None):
        super().__init__()
        self.session = session
        self.screenshot = screenshot
        self.hub = Hub(self)
        self._pending_play = None
        self.setWindowTitle("جلوه")
        self.setWindowIcon(app_icon())
        self.resize(1280, 800)
        self.setMinimumSize(1020, 680)

        self.root = QStackedWidget()
        self.setCentralWidget(self.root)
        shell = QWidget()
        shell.setObjectName("shell")
        shell_layout = QHBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        self.sidebar = self._build_sidebar()
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addWidget(self._build_topbar())
        self.stack = QStackedWidget()
        content_layout.addWidget(self.stack, 1)
        shell_layout.addWidget(self.sidebar)
        shell_layout.addWidget(content, 1)

        self.home = HomePage(session, self.hub)
        self.browse = BrowsePage(session, self.hub)
        self.search = SearchPage(session, self.hub)
        self.library = LibraryPage(session, self.hub)
        self.detail = DetailPage(session, self.hub)
        self.account = AccountPage(session, self.hub)
        self.player = PlayerPage(session.theme)
        self.player.volume.setValue(session.volume())
        for page in (self.home, self.browse, self.search, self.library, self.detail, self.account):
            self.stack.addWidget(page)
        self.root.addWidget(shell)
        self.root.addWidget(self.player)

        self.toast = Toast(shell, session.theme)
        self.hub.toast.connect(self.toast.show_message)
        self.hub.open_title.connect(self.open_title)
        self.hub.play_title.connect(self.play_title)
        self.hub.play_detail.connect(self.play_detail)
        self.hub.browse.connect(self.open_browse)
        self.hub.resume.connect(self.resume)
        self.hub.navigate.connect(self.navigate)
        self.hub.logged_in.connect(self._after_login)
        self.player.closed.connect(self._close_player)
        self.player.progress.connect(session.remember)
        self.player.volume.valueChanged.connect(session.set_volume)
        session.auth_changed.connect(self._auth_changed)
        session.theme.changed.connect(self._apply_theme)

        find = QAction(self)
        find.setShortcut(QKeySequence.StandardKey.Find)
        find.triggered.connect(lambda: self.navigate("search"))
        self.addAction(find)

        self.navigate("home")
        self._captured = False
        if session.api.token:
            session.restore_user()
            self._auth_changed()
            session.tasks.run(session.api.me, self._me_ok, self._me_failed)
        if screenshot:
            self.home.ready.connect(lambda: QTimer.singleShot(1600, self._capture))
            QTimer.singleShot(12000, self._capture)

    def _build_sidebar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("sidebar")
        bar.setFixedWidth(212)
        layout = QVBoxLayout(bar)
        layout.setContentsMargins(16, 20, 16, 20)
        layout.setSpacing(6)
        brand = QHBoxLayout()
        mark = QLabel()
        mark.setPixmap(logo_pixmap(34))
        word = QLabel("JELVEH")
        word.setObjectName("logoWord")
        brand.addWidget(mark)
        brand.addWidget(word)
        brand.addStretch(1)
        layout.addLayout(brand)
        caption = QLabel("تماشا و دانلود")
        caption.setObjectName("muted")
        layout.addWidget(caption)
        layout.addSpacing(16)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons = {}
        for key, label in (
            ("home", "خانه"),
            ("movies", "فیلم‌ها"),
            ("series", "سریال‌ها"),
            ("search", "جستجو"),
            ("library", "لیست من"),
            ("account", "حساب"),
        ):
            button = QPushButton(label)
            button.setObjectName("nav")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, key=key: self.navigate(key))
            self.nav_group.addButton(button)
            self.nav_buttons[key] = button
            layout.addWidget(button)
        layout.addStretch(1)
        version = QLabel(f"نسخه {__version__}")
        version.setObjectName("muted")
        layout.addWidget(version)
        return bar

    def _build_topbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("topbar")
        bar.setFixedHeight(72)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(22, 12, 22, 12)
        self.search_box = QLineEdit()
        self.search_box.setObjectName("search")
        self.search_box.setPlaceholderText("فیلم، سریال، برنامه...")
        self.search_box.returnPressed.connect(self._submit_search)
        self.theme_button = QPushButton("حالت روشن")
        self.theme_button.setObjectName("chip")
        self.theme_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.theme_button.clicked.connect(self.session.theme.toggle)
        self.account_button = QPushButton("ورود")
        self.account_button.setObjectName("primary")
        self.account_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.account_button.clicked.connect(lambda: self.navigate("account"))
        layout.addWidget(self.search_box, 1)
        layout.addWidget(self.theme_button)
        layout.addWidget(self.account_button)
        self._sync_account_button()
        self._sync_theme_button()
        return bar

    def navigate(self, key: str) -> None:
        if self.root.currentWidget() is self.player:
            self.player.close_player()
        mapping = {
            "home": self.home,
            "movies": self.browse,
            "series": self.browse,
            "search": self.search,
            "library": self.library,
            "account": self.account,
        }
        if key in ("movies", "series"):
            self.browse.open("movie" if key == "movies" else "series")
            self.nav_buttons[key].setChecked(True)
        elif key == "search":
            self.search.focus_search(self.search_box.text().strip() or None)
            self.nav_buttons["search"].setChecked(True)
        elif key in self.nav_buttons:
            self.nav_buttons[key].setChecked(True)
        widget = mapping.get(key, self.home)
        self._fade_to(widget)

    def _fade_to(self, widget: QWidget) -> None:
        self.stack.setCurrentWidget(widget)
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(180)
        animation.setStartValue(0.35)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.finished.connect(lambda: widget.setGraphicsEffect(None))
        animation.start()
        self._fade = animation

    def open_browse(self, kind: str, genre: str) -> None:
        self.browse.open(kind, genre or None)
        self.nav_buttons["movies" if kind == "movie" else "series"].setChecked(True)
        self._fade_to(self.browse)

    def open_title(self, kind: str, title_id: int) -> None:
        self.detail.open(kind, title_id)
        self._fade_to(self.detail)

    def play_title(self, kind: str, title_id: int) -> None:
        def load():
            detail = self.session.api.series_detail(title_id) if kind == "series" else self.session.api.movie(title_id)
            detail["type"] = kind
            episode = None
            if kind == "series":
                seasons = self.session.api.seasons(title_id)
                if seasons:
                    episodes = self.session.api.episodes(int(seasons[0]["id"]))
                    if episodes:
                        episode = self.session.api.episode(int(episodes[0]["id"]))
            return detail, episode

        self.session.tasks.run(
            load,
            lambda result: self.play_detail(result[0], result[1], None),
            self.hub.toast.emit,
        )

    def play_detail(self, detail: dict, episode: dict | None, index) -> None:
        if not self.session.user:
            self._pending_play = (detail, episode, index, 0)
            self.hub.toast.emit("برای پخش وارد حساب شوید.")
            self.navigate("account")
            return
        self._start_playback(detail, episode, index, 0)

    def resume(self, entry: dict) -> None:
        def load():
            kind = entry.get("type") or "movie"
            title_id = entry["id"]
            if kind == "series" or entry.get("episode_id"):
                detail = self.session.api.series_detail(title_id)
                detail["type"] = "series"
            else:
                detail = self.session.api.movie(title_id)
                detail["type"] = "movie"
            episode = self.session.api.episode(int(entry["episode_id"])) if entry.get("episode_id") else None
            return detail, episode, int(entry.get("position") or 0)

        self.session.tasks.run(load, lambda result: self._resume_ready(*result), self.hub.toast.emit)

    def _resume_ready(self, detail, episode, position: int) -> None:
        if not self.session.user:
            self._pending_play = (detail, episode, None, position)
            self.hub.toast.emit("برای ادامه تماشا وارد حساب شوید.")
            self.navigate("account")
            return
        self._start_playback(detail, episode, None, position)

    def _start_playback(self, detail, episode, index, resume_ms: int) -> None:
        self.player.play(detail, episode, None if index is None else int(index), resume_ms)
        self.root.setCurrentWidget(self.player)

    def _close_player(self) -> None:
        self.root.setCurrentWidget(self.root.widget(0))

    def _submit_search(self) -> None:
        self.navigate("search")

    def _after_login(self) -> None:
        self._load_favorites()
        pending = self._pending_play
        self._pending_play = None
        if pending:
            detail, episode, index, resume_ms = pending
            self._start_playback(detail, episode, index, resume_ms)
        else:
            self.navigate("home")

    def _auth_changed(self) -> None:
        self._sync_account_button()
        if self.session.user:
            self._load_favorites()

    def _sync_account_button(self) -> None:
        user = self.session.user or {}
        if user:
            self.account_button.setText(user.get("name") or user.get("phone") or "حساب")
            self.account_button.setObjectName("chip")
        else:
            self.account_button.setText("ورود")
            self.account_button.setObjectName("primary")
        self.account_button.style().unpolish(self.account_button)
        self.account_button.style().polish(self.account_button)

    def _sync_theme_button(self) -> None:
        self.theme_button.setText("حالت روشن" if self.session.theme.mode == "dark" else "حالت تاریک")

    def _apply_theme(self) -> None:
        app = QApplication.instance()
        if app:
            app.setStyleSheet(stylesheet(self.session.theme))
        self._sync_theme_button()

    def _load_favorites(self) -> None:
        def load():
            mapping = {}
            page = 1
            while page <= 5:
                rows, meta = self.session.api.favorites(page)
                for favorite in rows:
                    item = favorite.get("item") or {}
                    if item.get("id"):
                        mapping[(item.get("type"), item.get("id"))] = favorite.get("id")
                last = int(meta.get("last_page") or 1)
                if page >= last:
                    break
                page += 1
            return mapping

        def apply(mapping):
            if self.session.user:
                self.session.favorites = mapping

        self.session.tasks.run(load, apply, lambda _message: None)

    def _me_ok(self, user: dict) -> None:
        self.session.set_session({"user": user, "token": self.session.api.token})

    def _me_failed(self, message: str) -> None:
        if "اتصال" in message or "طول کشید" in message:
            return
        self.session.set_session(None)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.toast.isVisible():
            self.toast.show_message(self.toast.text())

    def _capture(self) -> None:
        if not self.screenshot or self._captured:
            return
        self._captured = True
        self.grab().save(self.screenshot)
        from PySide6.QtCore import QThreadPool

        QThreadPool.globalInstance().clear()
        QTimer.singleShot(30, QApplication.instance().quit)

    def closeEvent(self, event) -> None:
        self.session.settings.setValue("window/geometry", self.saveGeometry())
        super().closeEvent(event)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv if argv is None else argv)
    screenshot = None
    if "--screenshot" in args:
        index = args.index("--screenshot")
        screenshot = args[index + 1] if index + 1 < len(args) else "jelveh-home.png"

    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    qt_args = [args[0] if args else "jelveh"]
    app = QApplication(qt_args)
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    app.setApplicationName("جلوه")
    app.setOrganizationName("jelveh.top")
    app.setStyle("Fusion")
    family = load_fonts()
    session = Session()
    session.theme.family = family
    app.setFont(app_font(family))
    app.setStyleSheet(stylesheet(session.theme))
    window = MainWindow(session, screenshot=screenshot)
    geometry = session.settings.value("window/geometry")
    if geometry and not screenshot:
        window.restoreGeometry(geometry)
    elif screenshot:
        window.resize(1280, 800)
    window.show()
    if screenshot:
        screen = QGuiApplication.primaryScreen()
        if screen:
            window.move(screen.availableGeometry().center() - window.rect().center())
    return app.exec()
