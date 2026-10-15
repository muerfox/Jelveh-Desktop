"""Home, browse, search, detail, library, and account pages."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .api import link_label, normalize_links
from .widgets import BusyOverlay, FlowGrid, Hero, PosterCard, PosterRow, SmoothScroll, card_from, rating_text


class Page(QWidget):
    def __init__(self, session, hub):
        super().__init__()
        self.session = session
        self.hub = hub
        self.setObjectName("page")
        self.busy = BusyOverlay(self, session.theme)
        self._generation = 0

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.busy.reposition()

    def track(self, fn, ok) -> None:
        generation = self._generation

        def success(result, generation=generation):
            if generation != self._generation:
                return
            ok(result)

        def failure(message, generation=generation):
            if generation != self._generation:
                return
            self.busy.hide()
            self.hub.toast.emit(message)

        self.busy.reposition()
        self.busy.show()
        self.session.tasks.run(fn, success, failure)

    def invalidate(self) -> None:
        self._generation += 1
        self.busy.hide()


def _scroll() -> tuple[QScrollArea, QWidget, QVBoxLayout]:
    area = QScrollArea()
    area.setWidgetResizable(True)
    canvas = QWidget()
    canvas.setObjectName("canvas")
    layout = QVBoxLayout(canvas)
    layout.setContentsMargins(28, 22, 28, 40)
    layout.setSpacing(18)
    area.setWidget(canvas)
    return area, canvas, layout


class HomePage(Page):
    ready = Signal()

    def __init__(self, session, hub):
        super().__init__(session, hub)
        self.loaded = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.area, _canvas, self.layout = _scroll()
        outer.addWidget(self.area)
        self.hero = Hero(session.images, session.theme)
        self.hero.play_clicked.connect(self._play)
        self.hero.info_clicked.connect(lambda item: self.hub.open_title.emit(item["type"], int(item["id"])))
        self.layout.addWidget(self.hero)
        self.chips_scroll = SmoothScroll()
        self.chips_scroll.setFixedHeight(48)
        chips_host = QWidget()
        chips_host.setObjectName("canvas")
        self.chips = QHBoxLayout(chips_host)
        self.chips.setContentsMargins(0, 0, 0, 0)
        self.chips.setSpacing(8)
        self.chips_scroll.setWidget(chips_host)
        self.layout.addWidget(self.chips_scroll)
        self.rows_host = QVBoxLayout()
        self.rows_host.setSpacing(8)
        self.layout.addLayout(self.rows_host)
        self.layout.addStretch(1)
        self._rows: list[PosterRow] = []
        self._history_dirty = False
        session.history_changed.connect(self._mark_history)

    def _mark_history(self) -> None:
        self._history_dirty = True

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self.loaded or self._history_dirty:
            self._history_dirty = False
            self.reload()

    def reload(self) -> None:
        self.loaded = True
        self.invalidate()
        self.track(self.session.api.home, self._render_home)
        self.session.tasks.run(self.session.api.genres, self._render_genres, lambda _message: None)

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _render_genres(self, genres: list[dict]) -> None:
        self._clear_layout(self.chips)
        label = QLabel("ژانرها")
        label.setObjectName("muted")
        self.chips.addWidget(label)
        for genre in genres[:18]:
            button = QPushButton(genre.get("name") or "")
            button.setObjectName("chip")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            slug = genre.get("slug") or genre.get("name")
            button.clicked.connect(lambda _checked=False, slug=slug: self.hub.browse.emit("movie", slug))
            self.chips.addWidget(button)
        self.chips.addStretch(1)

    def _render_home(self, sections: list[dict]) -> None:
        self.busy.hide()
        self._clear_layout(self.rows_host)
        self._rows.clear()
        history = self.session.history()
        if history:
            row = PosterRow("ادامه تماشا")
            cards = []
            for entry in history[:16]:
                card = PosterCard(card_from(entry), self.session.images, self.session.theme)
                card.clicked.connect(lambda _item, entry=entry: self.hub.resume.emit(entry))
                cards.append(card)
            row.set_cards(cards)
            self.rows_host.addWidget(row)
        slides = []
        for section in sections:
            if section.get("type") == "slider" and section.get("items"):
                for item in section["items"]:
                    slide = card_from(item)
                    slide["backdrop"] = section.get("image") or slide.get("poster")
                    slides.append(slide)
                break
        if not slides:
            for section in sections:
                for item in section.get("items") or []:
                    slides.append(card_from(item))
                    if len(slides) >= 6:
                        break
                if slides:
                    break
        self.hero.set_slides(slides)
        for slide in slides:
            if slide.get("overview"):
                continue
            kind = slide["type"]
            title_id = slide["id"]
            self.session.tasks.run(
                lambda kind=kind, title_id=title_id: self._detail(kind, title_id),
                lambda detail, title_id=title_id: self.hero.update_slide(
                    title_id,
                    {
                        "overview": detail.get("overview") or "",
                        "backdrop": detail.get("backdrop") or detail.get("poster"),
                        "year": detail.get("release_year"),
                        "title": detail.get("title") or "",
                        "rating": detail.get("rating"),
                    },
                ),
                lambda _message: None,
            )
        for section in sections:
            items = section.get("items") or []
            if not items:
                continue
            row = PosterRow(section.get("title") or "")
            cards = []
            for item in items:
                data = card_from(item)
                card = PosterCard(data, self.session.images, self.session.theme)
                card.clicked.connect(lambda item: self.hub.open_title.emit(item["type"], int(item["id"])))
                cards.append(card)
            row.set_cards(cards)
            self.rows_host.addWidget(row)
            self._rows.append(row)
        self.ready.emit()

    def _detail(self, kind: str, title_id: int) -> dict:
        if kind == "series":
            return self.session.api.series_detail(title_id)
        return self.session.api.movie(title_id)

    def _play(self, item: dict) -> None:
        self.hub.play_title.emit(item["type"], int(item["id"]))


class BrowsePage(Page):
    def __init__(self, session, hub):
        super().__init__(session, hub)
        self.kind = "movie"
        self.page = 1
        self.last_page = 1
        self.genre = ""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 18, 28, 12)
        outer.setSpacing(12)
        filters = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("جستجو در عنوان‌ها")
        self.query.returnPressed.connect(self.reload)
        self.genre_box = QComboBox()
        self.genre_box.addItem("همه ژانرها", "")
        self.sort_box = QComboBox()
        self.sorts = [
            ("تازه‌ترین", "created_at", "desc"),
            ("بالاترین امتیاز", "rating", "desc"),
            ("محبوب‌ترین", "popularity", "desc"),
            ("سال ساخت", "release_year", "desc"),
            ("الفبا", "title", "asc"),
        ]
        for label, _sort, _direction in self.sorts:
            self.sort_box.addItem(label)
        self.year = QLineEdit()
        self.year.setPlaceholderText("سال")
        self.year.setFixedWidth(90)
        self.year.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.rating = QComboBox()
        for label, value in (("هر امتیاز", ""), ("از 6", "6"), ("از 7", "7"), ("از 8", "8"), ("از 9", "9")):
            self.rating.addItem(label, value)
        apply_button = QPushButton("اعمال")
        apply_button.setObjectName("primary")
        apply_button.clicked.connect(self.reload)
        filters.addWidget(self.query, 1)
        filters.addWidget(self.genre_box)
        filters.addWidget(self.sort_box)
        filters.addWidget(self.year)
        filters.addWidget(self.rating)
        filters.addWidget(apply_button)
        outer.addLayout(filters)
        self.area, _canvas, column = _scroll()
        self.grid = FlowGrid()
        column.addWidget(self.grid)
        self.more = QPushButton("نمایش بیشتر")
        self.more.setObjectName("chip")
        self.more.clicked.connect(self._more)
        self.more.hide()
        column.addWidget(self.more, alignment=Qt.AlignmentFlag.AlignCenter)
        column.addStretch(1)
        outer.addWidget(self.area, 1)
        self._genres_ready = False

    def open(self, kind: str, genre: str | None = None) -> None:
        self.kind = kind
        self.genre = genre or ""
        self._ensure_genres()
        self.reload()

    def _ensure_genres(self) -> None:
        if self._genres_ready:
            self._select_genre()
            return
        self.session.tasks.run(self.session.api.genres, self._fill_genres, lambda message: self.hub.toast.emit(message))

    def _fill_genres(self, genres: list[dict]) -> None:
        self._genres_ready = True
        current = self.genre_box.currentData()
        self.genre_box.clear()
        self.genre_box.addItem("همه ژانرها", "")
        for genre in genres:
            self.genre_box.addItem(genre.get("name") or "", genre.get("slug") or genre.get("name"))
        self._select_genre(current)
        if self.genre:
            self.reload()

    def _select_genre(self, fallback: str | None = None) -> None:
        wanted = self.genre or fallback or ""
        index = max(0, self.genre_box.findData(wanted))
        self.genre_box.setCurrentIndex(index)

    def reload(self) -> None:
        self.invalidate()
        self.page = 1
        self._load(append=False)

    def _more(self) -> None:
        if self.page < self.last_page:
            self.page += 1
            self._load(append=True)

    def _load(self, append: bool) -> None:
        _label, sort, direction = self.sorts[self.sort_box.currentIndex()]
        year = self.year.text().strip()
        params = {
            "page": self.page,
            "per_page": 24,
            "sort": sort,
            "direction": direction,
            "search": self.query.text().strip(),
            "genre": self.genre_box.currentData() or self.genre or "",
            "year": year if year.isdigit() else "",
            "rating": self.rating.currentData() or "",
        }
        call = self.session.api.movies if self.kind == "movie" else self.session.api.series
        self.track(lambda: call(**params), lambda result, append=append: self._show(result, append))

    def _show(self, result, append: bool) -> None:
        self.busy.hide()
        rows, meta = result
        self.last_page = int(meta.get("last_page") or 1)
        cards = []
        for item in rows:
            data = card_from(item, self.kind)
            card = PosterCard(data, self.session.images, self.session.theme)
            card.clicked.connect(lambda item: self.hub.open_title.emit(item["type"], int(item["id"])))
            cards.append(card)
        self.grid.set_cards(cards, append=append)
        self.more.setVisible(self.page < self.last_page)
        if not append and not cards:
            self.hub.toast.emit("چیزی با این فیلتر پیدا نشد.")


class SearchPage(Page):
    def __init__(self, session, hub):
        super().__init__(session, hub)
        self.page = 1
        self.query_text = ""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 18, 28, 12)
        self.box = QLineEdit()
        self.box.setObjectName("search")
        self.box.setPlaceholderText("فیلم، سریال، بازیگر…")
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(320)
        self._debounce.timeout.connect(self.reload)
        self.box.textChanged.connect(lambda _text: self._debounce.start())
        outer.addWidget(self.box)
        self.area, _canvas, column = _scroll()
        self.grid = FlowGrid()
        self.empty = QLabel("نام فیلم، سریال یا بازیگر را بنویسید.")
        self.empty.setObjectName("muted")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(self.empty)
        column.addWidget(self.grid)
        self.more = QPushButton("نتایج بیشتر")
        self.more.setObjectName("chip")
        self.more.clicked.connect(self._more)
        self.more.hide()
        column.addWidget(self.more, alignment=Qt.AlignmentFlag.AlignCenter)
        column.addStretch(1)
        outer.addWidget(self.area, 1)

    def focus_search(self, text: str | None = None) -> None:
        if text is not None and text != self.box.text():
            self.box.setText(text)
        self.box.setFocus()

    def reload(self) -> None:
        self.invalidate()
        self.page = 1
        self.query_text = self.box.text().strip()
        if len(self.query_text) < 1:
            self.grid.set_cards([])
            self.empty.setText("نام فیلم، سریال یا بازیگر را بنویسید.")
            self.empty.show()
            self.more.hide()
            return
        self._load(append=False)

    def _more(self) -> None:
        self.page += 1
        self._load(append=True)

    def _load(self, append: bool) -> None:
        text = self.query_text
        page = self.page
        self.track(lambda: self.session.api.search(text, page), lambda result, append=append: self._show(result, append))

    def _show(self, result, append: bool) -> None:
        self.busy.hide()
        rows, meta = result
        cards = []
        for item in rows:
            data = card_from(item)
            card = PosterCard(data, self.session.images, self.session.theme)
            card.clicked.connect(lambda item: self.hub.open_title.emit(item["type"], int(item["id"])))
            cards.append(card)
        self.grid.set_cards(cards, append=append)
        self.empty.setVisible(not self.grid.cards)
        self.empty.setText("نتیجه‌ای پیدا نشد.")
        last = int(meta.get("last_page") or 1)
        self.more.setVisible(self.page < last)


class SpoilerLabel(QLabel):
    def __init__(self, text: str, spoil: bool):
        super().__init__("این نظر حاوی اسپویل است. برای دیدن کلیک کنید." if spoil else text)
        self._text = text
        self._hidden = spoil
        if spoil:
            self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event) -> None:
        if self._hidden and event.button() == Qt.MouseButton.LeftButton:
            self._hidden = False
            self.setText(self._text)
        super().mouseReleaseEvent(event)


class DetailPage(Page):
    def __init__(self, session, hub):
        super().__init__(session, hub)
        self.kind = "movie"
        self.title_id = 0
        self.detail: dict = {}
        self.seasons: list[dict] = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.area, _canvas, self.body = _scroll()
        outer.addWidget(self.area)
        self.banner = QLabel()
        self.banner.setMinimumHeight(280)
        self.banner.setMaximumHeight(360)
        self.banner.setAlignment(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)
        self.body.addWidget(self.banner)
        self.heading = QLabel("")
        self.heading.setObjectName("section")
        self.heading.setStyleSheet("font-size: 28px;")
        self.meta = QLabel("")
        self.meta.setObjectName("dim")
        self.overview = QLabel("")
        self.overview.setWordWrap(True)
        self.overview.setObjectName("dim")
        actions = QHBoxLayout()
        self.play_button = QPushButton("پخش")
        self.play_button.setObjectName("primary")
        self.play_button.clicked.connect(lambda: self.hub.play_detail.emit(self.detail, None, None))
        self.fav_button = QPushButton("افزودن به علاقه‌مندی")
        self.fav_button.setObjectName("chip")
        self.fav_button.clicked.connect(self._toggle_favorite)
        self.like_button = QPushButton("پسندیدم")
        self.dislike_button = QPushButton("نپسندیدم")
        self.like_button.setObjectName("chip")
        self.dislike_button.setObjectName("chip")
        self.like_button.clicked.connect(lambda: self._react("like"))
        self.dislike_button.clicked.connect(lambda: self._react("dislike"))
        self.list_button = QPushButton("افزودن به پلی‌لیست")
        self.list_button.setObjectName("chip")
        self.list_button.clicked.connect(self._add_to_playlist)
        for button in (self.play_button, self.fav_button, self.like_button, self.dislike_button, self.list_button):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            actions.addWidget(button)
        actions.addStretch(1)
        self.body.addWidget(self.heading)
        self.body.addWidget(self.meta)
        self.body.addLayout(actions)
        self.body.addWidget(self.overview)
        self.cast_row = QHBoxLayout()
        self.body.addLayout(self.cast_row)
        self.season_box = QComboBox()
        self.season_box.currentIndexChanged.connect(self._season_changed)
        self.season_box.hide()
        self.body.addWidget(self.season_box)
        self.episodes = QVBoxLayout()
        self.body.addLayout(self.episodes)
        self.links_box = QVBoxLayout()
        self.body.addLayout(self.links_box)
        comment_title = QLabel("نظرها")
        comment_title.setObjectName("section")
        self.body.addWidget(comment_title)
        self.comment_input = QTextEdit()
        self.comment_input.setPlaceholderText("نظر شما…")
        self.comment_input.setFixedHeight(90)
        self.spoil = QPushButton("حاوی اسپویل")
        self.spoil.setCheckable(True)
        self.spoil.setObjectName("chip")
        self.send = QPushButton("ثبت نظر")
        self.send.setObjectName("primary")
        self.send.clicked.connect(self._send_comment)
        comment_actions = QHBoxLayout()
        comment_actions.addWidget(self.spoil)
        comment_actions.addStretch(1)
        comment_actions.addWidget(self.send)
        self.body.addWidget(self.comment_input)
        self.body.addLayout(comment_actions)
        self.comments = QVBoxLayout()
        self.body.addLayout(self.comments)
        self.body.addStretch(1)

    def open(self, kind: str, title_id: int) -> None:
        self.kind = kind
        self.title_id = title_id
        self.detail = {}
        self.invalidate()
        self.heading.setText("در حال بارگذاری…")
        self.track(lambda: self._fetch(), self._render)

    def _fetch(self):
        api = self.session.api
        if self.kind == "series":
            detail = api.series_detail(self.title_id)
            seasons = api.seasons(self.title_id)
            comments, _meta = api.comments("series", self.title_id)
            return detail, seasons, comments
        detail = api.movie(self.title_id)
        comments, _meta = api.comments("movie", self.title_id)
        return detail, [], comments

    def _render(self, payload) -> None:
        self.busy.hide()
        detail, seasons, comments = payload
        detail["type"] = self.kind
        self.detail = detail
        self.seasons = seasons or detail.get("seasons") or []
        self.heading.setText(detail.get("title") or "")
        bits = []
        if detail.get("release_year"):
            bits.append(str(detail["release_year"]))
        if detail.get("runtime"):
            bits.append(f"{detail['runtime']} دقیقه")
        score = rating_text(detail)
        if score:
            bits.append(f"امتیاز {score}")
        if detail.get("age_rating"):
            bits.append(str(detail["age_rating"]))
        genres = "، ".join(genre.get("name") or "" for genre in detail.get("genres") or [])
        if genres:
            bits.append(genres)
        self.meta.setText("   ·   ".join(bit for bit in bits if bit))
        self.overview.setText(detail.get("overview") or "خلاصه‌ای ثبت نشده است.")
        self._set_banner(detail.get("backdrop") or detail.get("poster"))
        self._render_cast(detail.get("casts") or [])
        self._render_links(normalize_links(detail.get("download_links")))
        self._render_seasons()
        self._render_comments(comments or [])
        self._sync_favorite()
        likes = detail.get("likes_count")
        dislikes = detail.get("dislikes_count")
        if likes is not None:
            self.like_button.setText(f"پسندیدم  {likes}")
            self.dislike_button.setText(f"نپسندیدم  {dislikes or 0}")

    def _set_banner(self, url: str | None) -> None:
        def apply(image, url=url):
            from .images import cover_pixmap

            self.banner.setPixmap(cover_pixmap(image, max(self.banner.width(), 640), 320, 18))

        self.session.images.load(url, apply)

    def _render_cast(self, casts: list[dict]) -> None:
        self._clear(self.cast_row)
        for person in casts[:14]:
            card = QFrame()
            card.setFixedWidth(92)
            column = QVBoxLayout(card)
            column.setContentsMargins(0, 0, 0, 0)
            photo = QLabel()
            photo.setFixedSize(72, 72)
            photo.setStyleSheet("background: #181818; border-radius: 36px;")
            name = QLabel(person.get("name") or "")
            name.setWordWrap(True)
            name.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name.setObjectName("muted")
            column.addWidget(photo, alignment=Qt.AlignmentFlag.AlignCenter)
            column.addWidget(name)

            def paint(image, photo=photo):
                from shiboken6 import isValid

                from .images import cover_pixmap

                if image is not None and isValid(photo):
                    photo.setPixmap(cover_pixmap(image, 72, 72, 36))

            self.session.images.load(person.get("photo"), paint)
            self.cast_row.addWidget(card)
        self.cast_row.addStretch(1)

    def _render_links(self, links: list[dict]) -> None:
        self._clear(self.links_box)
        if self.kind == "series":
            return
        if not links:
            note = QLabel("لینک پخشی برای این فیلم ثبت نشده است.")
            note.setObjectName("muted")
            self.links_box.addWidget(note)
            return
        title = QLabel("کیفیت‌ها")
        title.setObjectName("section")
        self.links_box.addWidget(title)
        for index, link in enumerate(links):
            button = QPushButton(link_label(link))
            button.setObjectName("chip")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, index=index: self.hub.play_detail.emit(self.detail, None, index))
            self.links_box.addWidget(button)

    def _render_seasons(self) -> None:
        self._clear(self.episodes)
        self.season_box.blockSignals(True)
        self.season_box.clear()
        visible = self.kind == "series" and bool(self.seasons)
        self.season_box.setVisible(visible)
        if not visible:
            self.season_box.blockSignals(False)
            return
        for season in self.seasons:
            number = season.get("season_number")
            label = season.get("name") or f"فصل {number}"
            self.season_box.addItem(label, season.get("id"))
        self.season_box.blockSignals(False)
        self._season_changed(self.season_box.currentIndex())

    def _season_changed(self, index: int) -> None:
        if index < 0:
            return
        season_id = self.season_box.currentData()
        if not season_id:
            return
        self.session.tasks.run(
            lambda: self.session.api.episodes(int(season_id)),
            self._render_episodes,
            lambda message: self.hub.toast.emit(message),
        )

    def _render_episodes(self, episodes: list[dict]) -> None:
        self._clear(self.episodes)
        if not episodes:
            note = QLabel("قسمتی برای این فصل ثبت نشده است.")
            note.setObjectName("muted")
            self.episodes.addWidget(note)
            return
        for episode in episodes:
            row = QFrame()
            row.setStyleSheet(f"background: {self.session.theme.palette.card}; border-radius: 12px;")
            layout = QHBoxLayout(row)
            number = QLabel(str(episode.get("episode_number") or ""))
            number.setObjectName("gold")
            number.setFixedWidth(36)
            title = QLabel(episode.get("name") or f"قسمت {episode.get('episode_number')}")
            title.setWordWrap(True)
            play = QPushButton("پخش")
            play.setObjectName("primary")
            play.setCursor(Qt.CursorShape.PointingHandCursor)
            play.clicked.connect(lambda _checked=False, episode=episode: self._play_episode(episode))
            layout.addWidget(number)
            layout.addWidget(title, 1)
            layout.addWidget(play)
            self.episodes.addWidget(row)

    def _play_episode(self, episode: dict) -> None:
        episode_id = episode.get("id")

        def load():
            full = self.session.api.episode(int(episode_id))
            full.setdefault("episode_number", episode.get("episode_number"))
            full.setdefault("name", episode.get("name"))
            return full

        self.session.tasks.run(
            load,
            lambda full: self.hub.play_detail.emit(self.detail, full, None),
            lambda message: self.hub.toast.emit(message),
        )

    def _render_comments(self, comments: list[dict]) -> None:
        self._clear(self.comments)
        if not comments:
            note = QLabel("هنوز نظری ثبت نشده است.")
            note.setObjectName("muted")
            self.comments.addWidget(note)
            return
        for comment in comments:
            self.comments.addWidget(self._comment_widget(comment))

    def _comment_widget(self, comment: dict) -> QWidget:
        frame = QFrame()
        frame.setStyleSheet(f"background: {self.session.theme.palette.surface}; border-radius: 12px;")
        layout = QVBoxLayout(frame)
        user = (comment.get("user") or {}).get("name") or "کاربر"
        head = QLabel(user)
        head.setObjectName("gold")
        body = SpoilerLabel(comment.get("body") or "", bool(comment.get("spoil")))
        body.setWordWrap(True)
        layout.addWidget(head)
        layout.addWidget(body)
        return frame

    def _send_comment(self) -> None:
        text = self.comment_input.toPlainText().strip()
        if not text:
            return
        if not self.session.user:
            self.hub.toast.emit("برای ثبت نظر وارد حساب شوید.")
            self.hub.navigate.emit("account")
            return
        kind = self.kind
        title_id = self.title_id
        spoil = self.spoil.isChecked()
        self.session.tasks.run(
            lambda: self.session.api.post_comment(kind, title_id, text, spoil),
            lambda _result: self._comment_sent(),
            lambda message: self.hub.toast.emit(message),
        )

    def _comment_sent(self) -> None:
        self.comment_input.clear()
        self.spoil.setChecked(False)
        self.hub.toast.emit("نظر ثبت شد و پس از تأیید نمایش داده می‌شود.")

    def _sync_favorite(self) -> None:
        saved = (self.kind, self.title_id) in self.session.favorites
        self.fav_button.setText("حذف از علاقه‌مندی" if saved else "افزودن به علاقه‌مندی")

    def _toggle_favorite(self) -> None:
        if not self.session.user:
            self.hub.toast.emit("برای علاقه‌مندی وارد حساب شوید.")
            self.hub.navigate.emit("account")
            return
        key = (self.kind, self.title_id)
        existing = self.session.favorites.get(key)

        def finish_add(payload):
            favorite_id = (payload or {}).get("id")
            if favorite_id:
                self.session.favorites[key] = favorite_id
            self._sync_favorite()
            self.hub.toast.emit("به علاقه‌مندی‌ها اضافه شد.")

        def finish_remove(_result):
            self.session.favorites.pop(key, None)
            self._sync_favorite()
            self.hub.toast.emit("از علاقه‌مندی‌ها حذف شد.")

        if existing:
            self.session.tasks.run(lambda: self.session.api.remove_favorite(existing), finish_remove, self.hub.toast.emit)
        else:
            self.session.tasks.run(
                lambda: self.session.api.add_favorite(self.kind, self.title_id),
                finish_add,
                self.hub.toast.emit,
            )

    def _react(self, reaction: str) -> None:
        if not self.session.user:
            self.hub.toast.emit("برای ثبت بازخورد وارد حساب شوید.")
            self.hub.navigate.emit("account")
            return
        kind = self.kind
        title_id = self.title_id
        self.session.tasks.run(
            lambda: self.session.api.react(kind, title_id, reaction),
            lambda payload: self._reacted(payload),
            self.hub.toast.emit,
        )

    def _reacted(self, payload: dict) -> None:
        self.like_button.setText(f"پسندیدم  {payload.get('likes_count', 0)}")
        self.dislike_button.setText(f"نپسندیدم  {payload.get('dislikes_count', 0)}")

    def _add_to_playlist(self) -> None:
        if not self.session.user:
            self.hub.toast.emit("برای پلی‌لیست وارد حساب شوید.")
            self.hub.navigate.emit("account")
            return
        self.session.tasks.run(self.session.api.playlists, self._choose_playlist, self.hub.toast.emit)

    def _choose_playlist(self, playlists: list[dict]) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("افزودن به پلی‌لیست")
        dialog.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("یک لیست را انتخاب کنید یا لیست تازه بسازید."))
        name = QLineEdit()
        name.setPlaceholderText("نام لیست تازه")
        layout.addWidget(name)
        buttons = []
        for playlist in playlists:
            button = QPushButton(playlist.get("name") or "لیست")
            button.setObjectName("chip")
            button.clicked.connect(lambda _checked=False, playlist=playlist: self._save_playlist(dialog, playlist["id"]))
            layout.addWidget(button)
            buttons.append(button)
        create = QPushButton("ساخت لیست و افزودن")
        create.setObjectName("primary")
        create.clicked.connect(lambda: self._create_and_add(dialog, name.text().strip()))
        layout.addWidget(create)
        dialog.resize(360, 280)
        dialog.exec()

    def _create_and_add(self, dialog: QDialog, name: str) -> None:
        if not name:
            self.hub.toast.emit("نام لیست را بنویسید.")
            return

        def created(playlist: dict):
            dialog.accept()
            self._save_playlist(None, playlist.get("id"))

        self.session.tasks.run(lambda: self.session.api.create_playlist(name), created, self.hub.toast.emit)

    def _save_playlist(self, dialog: QDialog | None, playlist_id: int | None) -> None:
        if dialog:
            dialog.accept()
        if not playlist_id:
            return
        kind = self.kind
        title_id = self.title_id
        self.session.tasks.run(
            lambda: self.session.api.add_playlist_item(int(playlist_id), kind, title_id),
            lambda _result: self.hub.toast.emit("به پلی‌لیست اضافه شد."),
            self.hub.toast.emit,
        )

    def _clear(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
            child = item.layout()
            if child:
                self._clear(child)


class LibraryPage(Page):
    def __init__(self, session, hub):
        super().__init__(session, hub)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 18, 28, 12)
        header = QHBoxLayout()
        self.fav_tab = QPushButton("علاقه‌مندی‌ها")
        self.list_tab = QPushButton("پلی‌لیست‌ها")
        for button in (self.fav_tab, self.list_tab):
            button.setCheckable(True)
            button.setObjectName("chip")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.fav_tab.setChecked(True)
        self.fav_tab.clicked.connect(lambda: self._show_tab("favorites"))
        self.list_tab.clicked.connect(lambda: self._show_tab("playlists"))
        header.addWidget(self.fav_tab)
        header.addWidget(self.list_tab)
        header.addStretch(1)
        outer.addLayout(header)
        self.area, _canvas, self.column = _scroll()
        outer.addWidget(self.area, 1)
        self.grid = FlowGrid()
        self.column.addWidget(self.grid)
        self.lists = QVBoxLayout()
        self.column.addLayout(self.lists)
        self.column.addStretch(1)
        self.mode = "favorites"

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.reload()

    def reload(self) -> None:
        if not self.session.user:
            self.grid.set_cards([])
            self._clear(self.lists)
            note = QLabel("برای دیدن لیست خود وارد حساب شوید.")
            note.setObjectName("muted")
            self.lists.addWidget(note)
            return
        if self.mode == "favorites":
            self.track(lambda: self.session.api.favorites(), self._show_favorites)
        else:
            self.track(self.session.api.playlists, self._show_playlists)

    def _show_tab(self, mode: str) -> None:
        self.mode = mode
        self.fav_tab.setChecked(mode == "favorites")
        self.list_tab.setChecked(mode == "playlists")
        self.reload()

    def _show_favorites(self, result) -> None:
        self.busy.hide()
        self._clear(self.lists)
        rows, _meta = result
        self.session.favorites = {}
        cards = []
        for favorite in rows:
            data = card_from(favorite)
            if data.get("id"):
                self.session.favorites[(data["type"], data["id"])] = favorite.get("id")
            card = PosterCard(data, self.session.images, self.session.theme)
            card.clicked.connect(lambda item: self.hub.open_title.emit(item["type"], int(item["id"])))
            cards.append(card)
        self.grid.set_cards(cards)
        if not cards:
            note = QLabel("هنوز چیزی به علاقه‌مندی‌ها اضافه نشده است.")
            note.setObjectName("muted")
            self.lists.addWidget(note)

    def _show_playlists(self, playlists: list[dict]) -> None:
        self.busy.hide()
        self.grid.set_cards([])
        self._clear(self.lists)
        create = QPushButton("لیست تازه")
        create.setObjectName("primary")
        create.clicked.connect(self._create)
        self.lists.addWidget(create, alignment=Qt.AlignmentFlag.AlignRight)
        if not playlists:
            note = QLabel("پلی‌لیستی ندارید.")
            note.setObjectName("muted")
            self.lists.addWidget(note)
            return
        for playlist in playlists:
            button = QPushButton(f"{playlist.get('name') or 'لیست'}   ·   {playlist.get('items_count') or 0} عنوان")
            button.setObjectName("chip")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, playlist=playlist: self._open_playlist(playlist["id"]))
            self.lists.addWidget(button)

    def _create(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("لیست تازه")
        dialog.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        layout = QVBoxLayout(dialog)
        name = QLineEdit()
        name.setPlaceholderText("نام لیست")
        layout.addWidget(name)
        save = QPushButton("ساخت")
        save.setObjectName("primary")
        layout.addWidget(save)

        def submit():
            text = name.text().strip()
            if not text:
                return
            dialog.accept()
            self.session.tasks.run(
                lambda: self.session.api.create_playlist(text),
                lambda _result: self.reload(),
                self.hub.toast.emit,
            )

        save.clicked.connect(submit)
        dialog.exec()

    def _open_playlist(self, playlist_id: int) -> None:
        self.track(lambda: self.session.api.playlist(playlist_id), self._render_playlist)

    def _render_playlist(self, playlist: dict) -> None:
        self.busy.hide()
        self._clear(self.lists)
        title = QLabel(playlist.get("name") or "")
        title.setObjectName("section")
        self.lists.addWidget(title)
        back = QPushButton("بازگشت به لیست‌ها")
        back.setObjectName("text")
        back.clicked.connect(lambda: self._show_tab("playlists"))
        self.lists.addWidget(back, alignment=Qt.AlignmentFlag.AlignRight)
        cards = []
        for entry in playlist.get("items") or []:
            data = card_from(entry)
            card = PosterCard(data, self.session.images, self.session.theme)
            card.clicked.connect(lambda item: self.hub.open_title.emit(item["type"], int(item["id"])))
            cards.append(card)
        self.grid.set_cards(cards)

    def _clear(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()


class AccountPage(Page):
    def __init__(self, session, hub):
        super().__init__(session, hub)
        outer = QVBoxLayout(self)
        outer.addStretch(1)
        self.card = QFrame()
        self.card.setMaximumWidth(440)
        column = QVBoxLayout(self.card)
        column.setContentsMargins(28, 28, 28, 28)
        column.setSpacing(12)
        self.title = QLabel("ورود")
        self.title.setObjectName("section")
        self.hint = QLabel("با شماره موبایل وارد شوید تا پخش، علاقه‌مندی و نظرها فعال شود.")
        self.hint.setWordWrap(True)
        self.hint.setObjectName("muted")
        self.name = QLineEdit()
        self.name.setPlaceholderText("نام (اختیاری)")
        self.phone = QLineEdit()
        self.phone.setPlaceholderText("09123456789")
        self.phone.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.password = QLineEdit()
        self.password.setPlaceholderText("رمز عبور")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.password.returnPressed.connect(self._submit)
        self.submit = QPushButton("ورود")
        self.submit.setObjectName("primary")
        self.switch = QPushButton("حساب ندارید؟ ثبت‌نام")
        self.switch.setObjectName("text")
        self.logout_button = QPushButton("خروج از حساب")
        self.logout_button.setObjectName("chip")
        self.profile = QLabel("")
        self.profile.setWordWrap(True)
        self.mode = "login"
        self.submit.clicked.connect(self._submit)
        self.switch.clicked.connect(self._toggle_mode)
        self.logout_button.clicked.connect(self.session.logout)
        for widget in (
            self.title,
            self.hint,
            self.profile,
            self.name,
            self.phone,
            self.password,
            self.submit,
            self.switch,
            self.logout_button,
        ):
            column.addWidget(widget)
        outer.addWidget(self.card, alignment=Qt.AlignmentFlag.AlignCenter)
        outer.addStretch(2)
        self.session.auth_changed.connect(self.refresh)
        self._restyle()
        self.session.theme.changed.connect(self._restyle)
        self.refresh()

    def _restyle(self) -> None:
        c = self.session.theme.palette
        self.card.setStyleSheet(f"background: {c.surface}; border: 1px solid {c.line}; border-radius: 20px;")

    def refresh(self) -> None:
        logged_in = bool(self.session.user)
        self.profile.setVisible(logged_in)
        self.logout_button.setVisible(logged_in)
        self.name.setVisible(not logged_in and self.mode == "register")
        for widget in (self.phone, self.password, self.submit, self.switch, self.hint):
            widget.setVisible(not logged_in)
        if logged_in:
            user = self.session.user or {}
            self.title.setText("حساب شما")
            self.profile.setText(f"{user.get('name') or 'کاربر جلوه'}\n{user.get('phone') or user.get('email') or ''}")
        else:
            self._apply_mode()

    def _toggle_mode(self) -> None:
        self.mode = "register" if self.mode == "login" else "login"
        self._apply_mode()

    def _apply_mode(self) -> None:
        register = self.mode == "register"
        self.title.setText("ثبت‌نام" if register else "ورود")
        self.submit.setText("ساخت حساب" if register else "ورود")
        self.switch.setText("حساب دارید؟ ورود" if register else "حساب ندارید؟ ثبت‌نام")
        self.name.setVisible(register and not self.session.user)
        self.hint.setText(
            "رمز حداقل ۸ کاراکتر با حرف بزرگ، حرف کوچک، عدد و نماد باشد."
            if register
            else "با شماره موبایل وارد شوید تا پخش، علاقه‌مندی و نظرها فعال شود."
        )

    def _submit(self) -> None:
        phone = self.phone.text().strip()
        password = self.password.text()
        if not phone or not password:
            self.hub.toast.emit("شماره و رمز را وارد کنید.")
            return
        if self.mode == "register":
            name = self.name.text().strip()
            call = lambda: self.session.api.register(phone, password, name)
        else:
            call = lambda: self.session.api.login_phone(phone, password)
        self.submit.setEnabled(False)
        self.session.tasks.run(call, self._logged_in, self._failed)

    def _logged_in(self, payload: dict) -> None:
        self.submit.setEnabled(True)
        self.session.set_session(payload)
        self.password.clear()
        self.hub.toast.emit("خوش آمدید.")
        self.hub.logged_in.emit()

    def _failed(self, message: str) -> None:
        self.submit.setEnabled(True)
        self.hub.toast.emit(message)
