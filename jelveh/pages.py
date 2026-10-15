"""Home, browse, search, detail, library, and account pages."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .api import link_label, normalize_links, preferred_link_index
from .downloads import format_bytes, format_eta, format_speed
from .theme import avatar_pixmap, dislike_icon, like_icon, moon_icon, rating_chip_pixmap, sun_icon
from .widgets import (
    BusyOverlay,
    CompactCombo,
    FlowGrid,
    Hero,
    PosterCard,
    PosterRow,
    SmoothScroll,
    TitleHero,
    card_from,
    rating_text,
)


class Page(QWidget):
    def __init__(self, session, hub):
        super().__init__()
        self.session = session
        self.hub = hub
        self.setObjectName("page")
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
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
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setAutoFillBackground(False)
    area.viewport().setAutoFillBackground(False)
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
            poster = slide.get("poster")
            self.session.tasks.run(
                lambda kind=kind, title_id=title_id: self._detail(kind, title_id),
                lambda detail, title_id=title_id, poster=poster: self.hero.update_slide(
                    title_id,
                    {
                        "overview": detail.get("overview") or "",
                        "backdrop": detail.get("backdrop") or detail.get("poster"),
                        "poster": detail.get("poster") or poster,
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
        self._loading = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 18, 28, 12)
        outer.setSpacing(12)
        filters = QHBoxLayout()
        self.genre_box = CompactCombo()
        self.genre_box.addItem("همه ژانرها", "")
        self.sort_box = CompactCombo()
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
        self.rating = CompactCombo()
        for label, value in (("هر امتیاز", ""), ("از 6", "6"), ("از 7", "7"), ("از 8", "8"), ("از 9", "9")):
            self.rating.addItem(label, value)
        apply_button = QPushButton("اعمال")
        apply_button.setObjectName("primary")
        apply_button.clicked.connect(self.reload)
        filters.addWidget(self.genre_box)
        filters.addWidget(self.sort_box)
        filters.addWidget(self.year)
        filters.addWidget(self.rating)
        filters.addWidget(apply_button)
        filters.addStretch(1)
        outer.addLayout(filters)
        self.area, _canvas, column = _scroll()
        self.grid = FlowGrid()
        column.addWidget(self.grid)
        column.addStretch(1)
        outer.addWidget(self.area, 1)
        self.area.verticalScrollBar().valueChanged.connect(self._on_scroll)
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
        self.last_page = 1
        self._loading = False
        self.area.verticalScrollBar().setValue(0)
        self._load(append=False)

    def _on_scroll(self, value: int) -> None:
        bar = self.area.verticalScrollBar()
        if self._loading or self.page >= self.last_page:
            return
        if bar.maximum() - value <= 360:
            self._more()

    def _more(self) -> None:
        if self._loading or self.page >= self.last_page:
            return
        self.page += 1
        self._load(append=True)

    def _load(self, append: bool) -> None:
        self._loading = True
        _label, sort, direction = self.sorts[max(0, self.sort_box.currentIndex())]
        year = self.year.text().strip()
        params = {
            "page": self.page,
            "per_page": 24,
            "sort": sort,
            "direction": direction,
            "genre": self.genre_box.currentData() or self.genre or "",
            "year": year if year.isdigit() else "",
            "rating": self.rating.currentData() or "",
        }
        call = self.session.api.movies if self.kind == "movie" else self.session.api.series
        generation = self._generation

        def success(result, generation=generation, append=append):
            if generation != self._generation:
                return
            self._loading = False
            self._show(result, append)

        def failure(message, generation=generation, append=append):
            if generation != self._generation:
                return
            self._loading = False
            if append and self.page > 1:
                self.page -= 1
            self.busy.hide()
            self.hub.toast.emit(message)

        if not append:
            self.busy.reposition()
            self.busy.show()
        self.session.tasks.run(lambda: call(**params), success, failure)

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
        if append and not cards:
            self.last_page = self.page
            return
        self.grid.set_cards(cards, append=append)
        if not append and not cards:
            self.hub.toast.emit("چیزی با این فیلتر پیدا نشد.")
            return
        QTimer.singleShot(0, self._fill_if_short)

    def _fill_if_short(self) -> None:
        bar = self.area.verticalScrollBar()
        if self.page < self.last_page and bar.maximum() <= 80:
            self._more()


class SearchPage(Page):
    def __init__(self, session, hub):
        super().__init__(session, hub)
        self.page = 1
        self.last_page = 1
        self._loading = False
        self.query_text = ""
        self._filters: dict = {}
        self._genres_ready = False
        self._countries_ready = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 18, 28, 12)
        outer.setSpacing(12)
        self.box = QLineEdit()
        self.box.setObjectName("search")
        self.box.setPlaceholderText("عنوان، خلاصه، بازیگر…")
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(380)
        self._debounce.timeout.connect(self.reload)
        self.box.textChanged.connect(lambda _text: self._debounce.start())
        self.box.returnPressed.connect(self.reload)
        outer.addWidget(self.box)

        filters = QFrame()
        filters.setObjectName("panel")
        filter_column = QVBoxLayout(filters)
        filter_column.setContentsMargins(14, 12, 14, 12)
        filter_column.setSpacing(10)
        heading = QLabel("جستجوی پیشرفته")
        heading.setObjectName("section")
        heading.setStyleSheet("font-size: 15px;")
        filter_column.addWidget(heading)

        row1 = QHBoxLayout()
        row1.setSpacing(8)
        self.type_box = CompactCombo()
        for label, value in (("همه انواع", "all"), ("فیلم", "movie"), ("سریال", "series")):
            self.type_box.addItem(label, value)
        self.genre_box = CompactCombo()
        self.genre_box.addItem("همه ژانرها", "")
        self.country_box = CompactCombo()
        self.country_box.addItem("همه کشورها", "")
        self.sort_box = CompactCombo()
        self.sorts = [
            ("مرتبط‌ترین", "relevance"),
            ("تازه‌ترین", "newest"),
            ("بالاترین امتیاز", "rating"),
            ("محبوب‌ترین", "popularity"),
            ("سال ساخت", "release_date"),
            ("الفبا", "title"),
        ]
        for label, _value in self.sorts:
            self.sort_box.addItem(label)
        for widget in (self.type_box, self.genre_box, self.country_box, self.sort_box):
            row1.addWidget(widget)
        filter_column.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        self.cast_box = QLineEdit()
        self.cast_box.setPlaceholderText("نام بازیگر")
        self.cast_box.returnPressed.connect(self.reload)
        self.year_from = QLineEdit()
        self.year_from.setPlaceholderText("از سال")
        self.year_from.setFixedWidth(88)
        self.year_from.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.year_from.returnPressed.connect(self.reload)
        self.year_to = QLineEdit()
        self.year_to.setPlaceholderText("تا سال")
        self.year_to.setFixedWidth(88)
        self.year_to.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.year_to.returnPressed.connect(self.reload)
        self.rating_box = CompactCombo()
        for label, value in (("هر امتیاز", ""), ("از ۶", "6"), ("از ۷", "7"), ("از ۸", "8"), ("از ۹", "9")):
            self.rating_box.addItem(label, value)
        apply_button = QPushButton("اعمال فیلتر")
        apply_button.setObjectName("primary")
        apply_button.setProperty("compact", True)
        apply_button.setCursor(Qt.CursorShape.PointingHandCursor)
        apply_button.clicked.connect(self.reload)
        clear_button = QPushButton("پاک‌سازی")
        clear_button.setObjectName("chip")
        clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_button.clicked.connect(self._clear_filters)
        row2.addWidget(self.cast_box, 1)
        row2.addWidget(self.year_from)
        row2.addWidget(self.year_to)
        row2.addWidget(self.rating_box)
        row2.addWidget(apply_button)
        row2.addWidget(clear_button)
        filter_column.addLayout(row2)
        outer.addWidget(filters)

        for combo in (self.type_box, self.genre_box, self.country_box, self.sort_box, self.rating_box):
            combo.currentIndexChanged.connect(lambda _index: self._debounce.start())

        self.area, _canvas, column = _scroll()
        self.grid = FlowGrid()
        self.empty = QLabel("عبارت جستجو یا فیلترها را تنظیم کنید.")
        self.empty.setObjectName("muted")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(self.empty)
        column.addWidget(self.grid)
        column.addStretch(1)
        outer.addWidget(self.area, 1)
        self.area.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self._ensure_taxonomies()

    def focus_search(self, text: str | None = None) -> None:
        self._ensure_taxonomies()
        if text is not None and text != self.box.text():
            self.box.setText(text)
        self.box.setFocus()

    def _ensure_taxonomies(self) -> None:
        if not self._genres_ready:
            self.session.tasks.run(self.session.api.genres, self._fill_genres, lambda _message: None)
        if not self._countries_ready:
            self.session.tasks.run(self.session.api.countries, self._fill_countries, lambda _message: None)

    def _fill_genres(self, genres: list[dict]) -> None:
        self._genres_ready = True
        current = self.genre_box.currentData()
        self.genre_box.blockSignals(True)
        self.genre_box.clear()
        self.genre_box.addItem("همه ژانرها", "")
        for genre in genres:
            name = genre.get("name") or ""
            if name:
                # API advanced-search matches Persian names/slugs; English TMDB slugs often miss.
                self.genre_box.addItem(name, name)
        index = max(0, self.genre_box.findData(current or ""))
        self.genre_box.setCurrentIndex(index)
        self.genre_box.blockSignals(False)

    def _fill_countries(self, countries: list[dict]) -> None:
        self._countries_ready = True
        current = self.country_box.currentData()
        self.country_box.blockSignals(True)
        self.country_box.clear()
        self.country_box.addItem("همه کشورها", "")
        for country in countries:
            name = country.get("name") or ""
            slug = country.get("slug") or ""
            if name and slug:
                self.country_box.addItem(name, slug)
        index = max(0, self.country_box.findData(current or ""))
        self.country_box.setCurrentIndex(index)
        self.country_box.blockSignals(False)

    def _clear_filters(self) -> None:
        for combo in (self.type_box, self.genre_box, self.country_box, self.sort_box, self.rating_box):
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
        self.cast_box.clear()
        self.year_from.clear()
        self.year_to.clear()
        self.reload()

    def _collect_filters(self) -> dict:
        year_from = self.year_from.text().strip()
        year_to = self.year_to.text().strip()
        content_type = self.type_box.currentData() or "all"
        sort = self.sorts[self.sort_box.currentIndex()][1]
        text = self.box.text().strip()
        if sort == "relevance" and not text:
            sort = "newest"
        filters = {
            "search": text,
            "type": "" if content_type == "all" else content_type,
            "genres": self.genre_box.currentData() or "",
            "countries": self.country_box.currentData() or "",
            "cast": self.cast_box.text().strip(),
            "year_from": int(year_from) if year_from.isdigit() else "",
            "year_to": int(year_to) if year_to.isdigit() else "",
            "rating_from": self.rating_box.currentData() or "",
            "sort": sort,
        }
        return filters

    def _has_criteria(self, filters: dict) -> bool:
        return any(
            filters.get(key)
            for key in ("search", "type", "genres", "countries", "cast", "year_from", "year_to", "rating_from")
        )

    def reload(self) -> None:
        self.invalidate()
        self.page = 1
        self.last_page = 1
        self._loading = False
        self._filters = self._collect_filters()
        self.query_text = str(self._filters.get("search") or "")
        self.area.verticalScrollBar().setValue(0)
        if not self._has_criteria(self._filters):
            self.grid.set_cards([])
            self.empty.setText("عبارت جستجو یا فیلترها را تنظیم کنید.")
            self.empty.show()
            return
        self._load(append=False)

    def _on_scroll(self, value: int) -> None:
        bar = self.area.verticalScrollBar()
        if self._loading or self.page >= self.last_page:
            return
        if bar.maximum() - value <= 360:
            self._more()

    def _more(self) -> None:
        if self._loading or self.page >= self.last_page:
            return
        self.page += 1
        self._load(append=True)

    def _load(self, append: bool) -> None:
        self._loading = True
        filters = dict(self._filters)
        page = self.page
        generation = self._generation

        def success(result, generation=generation, append=append):
            if generation != self._generation:
                return
            self._loading = False
            self._show(result, append)

        def failure(message, generation=generation, append=append):
            if generation != self._generation:
                return
            self._loading = False
            if append and self.page > 1:
                self.page -= 1
            self.busy.hide()
            self.hub.toast.emit(message)

        if not append:
            self.busy.reposition()
            self.busy.show()
        self.session.tasks.run(
            lambda: self.session.api.advanced_search(page=page, per_page=24, **filters),
            success,
            failure,
        )

    def _show(self, result, append: bool) -> None:
        self.busy.hide()
        rows, meta = result
        self.last_page = int(meta.get("last_page") or 1)
        cards = []
        for item in rows:
            data = card_from(item)
            card = PosterCard(data, self.session.images, self.session.theme)
            card.clicked.connect(lambda item: self.hub.open_title.emit(item["type"], int(item["id"])))
            cards.append(card)
        if append and not cards:
            self.last_page = self.page
            return
        self.grid.set_cards(cards, append=append)
        self.empty.setVisible(not self.grid.cards)
        if not self.grid.cards:
            self.empty.setText("نتیجه‌ای با این فیلتر پیدا نشد.")
            return
        QTimer.singleShot(0, self._fill_if_short)

    def _fill_if_short(self) -> None:
        bar = self.area.verticalScrollBar()
        if self.page < self.last_page and bar.maximum() <= 80:
            self._more()


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
        self.body.setContentsMargins(0, 0, 0, 40)
        outer.addWidget(self.area)
        self.hero = TitleHero(session.theme)
        self.heading = QLabel("")
        self.heading.setObjectName("heroTitle")
        self.heading.setWordWrap(True)
        self.heading.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute | Qt.AlignmentFlag.AlignVCenter
        )
        self.heading.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.heading.setStyleSheet("font-size: 36px; font-weight: 800; color: #ffffff; background: transparent;")
        self.meta = QLabel("")
        self.meta.setObjectName("heroMeta")
        self.meta.setWordWrap(True)
        self.meta.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute | Qt.AlignmentFlag.AlignVCenter
        )
        self.meta.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.meta.setStyleSheet("color: #f3f3f3; background: transparent; font-size: 14px;")
        self.rating_badge = QLabel()
        self.rating_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.rating_badge.hide()
        meta_row = QHBoxLayout()
        meta_row.setSpacing(10)
        meta_row.setContentsMargins(0, 0, 0, 0)
        meta_row.addWidget(self.rating_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        meta_row.addWidget(self.meta, 1)
        self.play_button = QPushButton("پخش")
        self.play_button.setObjectName("primary")
        self.play_button.clicked.connect(lambda: self.hub.play_detail.emit(self.detail, None, None))
        self.fav_button = QPushButton("افزودن به علاقه‌مندی")
        self.fav_button.setObjectName("ghost")
        self.fav_button.clicked.connect(self._toggle_favorite)
        actions = QHBoxLayout()
        actions.setSpacing(10)
        for button in (self.play_button, self.fav_button):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            actions.addWidget(button)
        actions.addStretch(1)
        self.hero.column.addWidget(self.heading)
        self.hero.column.addLayout(meta_row)
        self.hero.column.addLayout(actions)
        self.body.addWidget(self.hero)
        self.content = QVBoxLayout()
        self.content.setContentsMargins(28, 8, 28, 0)
        self.content.setSpacing(18)
        self.body.addLayout(self.content)
        self.overview = QLabel("")
        self.overview.setWordWrap(True)
        self.overview.setObjectName("dim")
        self.like_button = QPushButton("پسندیدم")
        self.dislike_button = QPushButton("نپسندیدم")
        self.like_button.setObjectName("chip")
        self.dislike_button.setObjectName("chip")
        self.like_button.setIcon(like_icon())
        self.dislike_button.setIcon(dislike_icon())
        self.like_button.setIconSize(QSize(18, 18))
        self.dislike_button.setIconSize(QSize(18, 18))
        self.like_button.clicked.connect(lambda: self._react("like"))
        self.dislike_button.clicked.connect(lambda: self._react("dislike"))
        self.list_button = QPushButton("افزودن به پلی‌لیست")
        self.list_button.setObjectName("chip")
        self.list_button.clicked.connect(self._add_to_playlist)
        reactions = QHBoxLayout()
        for button in (self.like_button, self.dislike_button, self.list_button):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            reactions.addWidget(button)
        reactions.addStretch(1)
        self.content.addWidget(self.overview)
        self.content.addLayout(reactions)
        self.cast_row = QHBoxLayout()
        self.content.addLayout(self.cast_row)
        self.season_box = CompactCombo()
        self.season_box.currentIndexChanged.connect(self._season_changed)
        self.season_box.hide()
        self.content.addWidget(self.season_box)
        self.episodes = QVBoxLayout()
        self.content.addLayout(self.episodes)
        self.links_box = QVBoxLayout()
        self.content.addLayout(self.links_box)
        comment_title = QLabel("نظرها")
        comment_title.setObjectName("section")
        self.content.addWidget(comment_title)
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
        self.content.addWidget(self.comment_input)
        self.content.addLayout(comment_actions)
        self.comments = QVBoxLayout()
        self.content.addLayout(self.comments)
        self.content.addStretch(1)

    def open(self, kind: str, title_id: int) -> None:
        self.kind = kind
        self.title_id = title_id
        self.detail = {}
        self.invalidate()
        self.hero.clear()
        self.meta.clear()
        self.rating_badge.clear()
        self.rating_badge.hide()
        self.overview.clear()
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
        if detail.get("age_rating"):
            bits.append(str(detail["age_rating"]))
        kind = "سریال" if self.kind == "series" else "فیلم"
        bits.append(kind)
        genres = "، ".join(genre.get("name") or "" for genre in detail.get("genres") or [])
        if genres:
            bits.append(genres)
        self.meta.setText("   ·   ".join(bit for bit in bits if bit))
        score = rating_text(detail)
        if score:
            self.rating_badge.setPixmap(rating_chip_pixmap(score))
            self.rating_badge.adjustSize()
            self.rating_badge.show()
        else:
            self.rating_badge.clear()
            self.rating_badge.hide()
        self.overview.setText(detail.get("overview") or "خلاصه‌ای ثبت نشده است.")
        self._set_banner(detail)
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

    def _set_banner(self, detail: dict) -> None:
        token = self.title_id

        def backdrop(image, token=token):
            if token != self.title_id:
                return
            self.hero.set_backdrop(image)

        def poster(image, token=token):
            if token != self.title_id:
                return
            self.hero.set_poster(image)

        self.session.images.load(detail.get("backdrop") or detail.get("poster"), backdrop)
        self.session.images.load(detail.get("poster") or detail.get("backdrop"), poster)

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
            row = QHBoxLayout()
            button = QPushButton(link_label(link))
            button.setObjectName("chip")
            button.setProperty("compact", True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, index=index: self.hub.play_detail.emit(self.detail, None, index))
            save = QPushButton("دانلود")
            save.setObjectName("chip")
            save.setProperty("compact", True)
            save.setCursor(Qt.CursorShape.PointingHandCursor)
            save.clicked.connect(lambda _checked=False, link=link: self._download_link(link))
            row.addWidget(button)
            row.addWidget(save)
            row.addStretch(1)
            self.links_box.addLayout(row)

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
            row.setStyleSheet(f"background: {self.session.theme.palette.card}; border-radius: 22px;")
            layout = QHBoxLayout(row)
            number = QLabel(str(episode.get("episode_number") or ""))
            number.setObjectName("gold")
            number.setFixedWidth(36)
            title = QLabel(episode.get("name") or f"قسمت {episode.get('episode_number')}")
            title.setWordWrap(True)
            play = QPushButton("پخش")
            play.setObjectName("primary")
            play.setProperty("compact", True)
            play.setCursor(Qt.CursorShape.PointingHandCursor)
            play.clicked.connect(lambda _checked=False, episode=episode: self._play_episode(episode))
            save = QPushButton("دانلود")
            save.setObjectName("chip")
            save.setProperty("compact", True)
            save.setCursor(Qt.CursorShape.PointingHandCursor)
            save.clicked.connect(lambda _checked=False, episode=episode: self._download_episode(episode))
            layout.addWidget(number)
            layout.addWidget(title, 1)
            layout.addWidget(save)
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

    def _download_link(self, link: dict) -> None:
        title = self.detail.get("title") or "جلوه"
        self.session.downloads.start(url=link["play_url"], title=title, detail=link_label(link))
        self.hub.toast.emit("دانلود شروع شد")
        self.hub.open_downloads.emit()

    def _download_episode(self, episode: dict) -> None:
        episode_id = episode.get("id")

        def load():
            full = self.session.api.episode(int(episode_id))
            full.setdefault("episode_number", episode.get("episode_number"))
            full.setdefault("name", episode.get("name"))
            return full

        def start(full: dict) -> None:
            links = normalize_links(full.get("download_links"))
            if not links:
                self.hub.toast.emit("لینک دانلودی برای این قسمت نیست.")
                return
            link = links[preferred_link_index(links)]
            number = full.get("episode_number") or ""
            title = f"{self.detail.get('title') or ''} قسمت {number}".strip()
            self.session.downloads.start(url=link["play_url"], title=title, detail=link_label(link))
            self.hub.toast.emit("دانلود قسمت شروع شد")
            self.hub.open_downloads.emit()

        self.session.tasks.run(load, start, lambda message: self.hub.toast.emit(message))

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
        frame.setStyleSheet(f"background: {self.session.theme.palette.surface}; border-radius: 22px;")
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
        dialog = PlaylistPickerDialog(self, self.session.theme, playlists)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if dialog.mode == "create":
            name, description = dialog.create_name, dialog.create_description
            self.session.tasks.run(
                lambda: self.session.api.create_playlist(name, description),
                lambda playlist: self._save_playlist(playlist.get("id")),
                self.hub.toast.emit,
            )
            return
        self._save_playlist(dialog.playlist_id)

    def _save_playlist(self, playlist_id: int | None) -> None:
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


class PlaylistEditorDialog(QDialog):
    """Create or rename a playlist with name + optional description."""

    def __init__(
        self,
        parent,
        theme,
        *,
        title: str = "پلی‌لیست تازه",
        name: str = "",
        description: str = "",
        submit_label: str = "ساخت پلی‌لیست",
    ):
        super().__init__(parent)
        self.theme = theme
        self.setWindowTitle(title)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(420)
        self.result_name = ""
        self.result_description = ""
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)
        heading = QLabel(title)
        heading.setObjectName("section")
        hint = QLabel("نام لیست را بنویسید. توضیح اختیاری است و فقط برای خودتان نمایش داده می‌شود.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        self.name = QLineEdit(name)
        self.name.setPlaceholderText("مثلاً تماشای آخر هفته")
        self.description = QTextEdit()
        self.description.setPlaceholderText("توضیح کوتاه (اختیاری)")
        self.description.setFixedHeight(88)
        if description:
            self.description.setPlainText(description)
        buttons = QDialogButtonBox()
        self.submit = buttons.addButton(submit_label, QDialogButtonBox.ButtonRole.AcceptRole)
        cancel = buttons.addButton("انصراف", QDialogButtonBox.ButtonRole.RejectRole)
        self.submit.setObjectName("primary")
        cancel.setObjectName("chip")
        self.submit.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.submit.clicked.connect(self._accept)
        cancel.clicked.connect(self.reject)
        self.name.returnPressed.connect(self._accept)
        root.addWidget(heading)
        root.addWidget(hint)
        root.addWidget(QLabel("نام"))
        root.addWidget(self.name)
        root.addWidget(QLabel("توضیح"))
        root.addWidget(self.description)
        root.addWidget(buttons)
        self.name.setFocus()
        self.name.selectAll()

    def _accept(self) -> None:
        text = self.name.text().strip()
        if not text:
            self.name.setFocus()
            self.name.setStyleSheet("border: 1px solid #e50914;")
            return
        self.result_name = text
        self.result_description = self.description.toPlainText().strip()
        self.accept()


class PlaylistPickerDialog(QDialog):
    """Pick an existing playlist or create one, then add the current title."""

    def __init__(self, parent, theme, playlists: list[dict]):
        super().__init__(parent)
        self.theme = theme
        self.mode = ""
        self.playlist_id: int | None = None
        self.create_name = ""
        self.create_description = ""
        self.setWindowTitle("افزودن به پلی‌لیست")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumSize(440, 460)
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)
        heading = QLabel("افزودن به پلی‌لیست")
        heading.setObjectName("section")
        hint = QLabel("یک لیست موجود را انتخاب کنید یا پلی‌لیست تازه بسازید.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        root.addWidget(heading)
        root.addWidget(hint)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        host = QWidget()
        host.setObjectName("canvas")
        self.list_layout = QVBoxLayout(host)
        self.list_layout.setContentsMargins(0, 0, 4, 0)
        self.list_layout.setSpacing(8)
        if playlists:
            for playlist in playlists:
                self.list_layout.addWidget(self._playlist_row(playlist))
        else:
            empty = QLabel("هنوز پلی‌لیستی ندارید. پایین همین پنجره یکی بسازید.")
            empty.setObjectName("muted")
            empty.setWordWrap(True)
            self.list_layout.addWidget(empty)
        self.list_layout.addStretch(1)
        scroll.setWidget(host)
        root.addWidget(scroll, 1)
        create_box = QFrame()
        create_box.setObjectName("panel")
        create_column = QVBoxLayout(create_box)
        create_column.setContentsMargins(14, 12, 14, 12)
        create_column.setSpacing(8)
        create_title = QLabel("ساخت پلی‌لیست تازه")
        create_title.setStyleSheet("font-weight: 700;")
        self.new_name = QLineEdit()
        self.new_name.setPlaceholderText("نام پلی‌لیست")
        self.new_description = QLineEdit()
        self.new_description.setPlaceholderText("توضیح (اختیاری)")
        create_button = QPushButton("ساخت و افزودن")
        create_button.setObjectName("primary")
        create_button.setCursor(Qt.CursorShape.PointingHandCursor)
        create_button.clicked.connect(self._create)
        self.new_name.returnPressed.connect(self._create)
        create_column.addWidget(create_title)
        create_column.addWidget(self.new_name)
        create_column.addWidget(self.new_description)
        create_column.addWidget(create_button, alignment=Qt.AlignmentFlag.AlignLeft)
        root.addWidget(create_box)

    def _playlist_row(self, playlist: dict) -> QFrame:
        card = QFrame()
        card.setObjectName("panel")
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        row = QHBoxLayout(card)
        row.setContentsMargins(14, 12, 14, 12)
        row.setSpacing(10)
        text = QVBoxLayout()
        text.setSpacing(2)
        name = QLabel(playlist.get("name") or "لیست")
        name.setStyleSheet("font-weight: 700; font-size: 14px;")
        count = int(playlist.get("items_count") or 0)
        meta = QLabel(f"{count} عنوان")
        meta.setObjectName("muted")
        description = (playlist.get("description") or "").strip()
        text.addWidget(name)
        if description:
            note = QLabel(description)
            note.setObjectName("dim")
            note.setWordWrap(True)
            text.addWidget(note)
        text.addWidget(meta)
        choose = QPushButton("افزودن")
        choose.setObjectName("chip")
        choose.setCursor(Qt.CursorShape.PointingHandCursor)
        choose.clicked.connect(lambda _checked=False, playlist_id=playlist.get("id"): self._pick(playlist_id))
        row.addLayout(text, 1)
        row.addWidget(choose, 0, Qt.AlignmentFlag.AlignVCenter)

        def press(event, playlist_id=playlist.get("id")):
            if event.button() == Qt.MouseButton.LeftButton:
                self._pick(playlist_id)

        card.mousePressEvent = press  # type: ignore[method-assign]
        return card

    def _pick(self, playlist_id: int | None) -> None:
        if not playlist_id:
            return
        self.mode = "pick"
        self.playlist_id = int(playlist_id)
        self.accept()

    def _create(self) -> None:
        name = self.new_name.text().strip()
        if not name:
            self.new_name.setFocus()
            self.new_name.setStyleSheet("border: 1px solid #e50914;")
            return
        self.mode = "create"
        self.create_name = name
        self.create_description = self.new_description.text().strip()
        self.accept()


class DownloadRow(QFrame):
    """One download card with live progress, pause, and cancel."""

    def __init__(self, item: dict, session, hub, parent=None):
        super().__init__(parent)
        self.session = session
        self.hub = hub
        self.item_id = item.get("id") or ""
        self.setObjectName("panel")
        self.setStyleSheet(f"background: {session.theme.palette.card}; border-radius: 22px;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        self.title = QLabel()
        self.title.setWordWrap(True)
        self.title.setStyleSheet("font-weight: 700; font-size: 15px;")
        self.detail = QLabel()
        self.detail.setObjectName("muted")
        self.detail.setWordWrap(True)
        self.meta_host = QWidget()
        self.meta_host.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.meta_row = QHBoxLayout(self.meta_host)
        self.meta_row.setContentsMargins(0, 0, 0, 0)
        self.meta_row.setSpacing(8)
        self._meta_labels = []
        for _ in range(8):
            label = QLabel()
            label.hide()
            self.meta_row.addWidget(label)
            self._meta_labels.append(label)
        self.meta_row.addStretch(1)
        self.bar = QProgressBar()
        self.bar.setObjectName("downloadBar")
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 100)
        self.bar.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.pause_button = QPushButton("توقف")
        self.pause_button.setObjectName("chip")
        self.pause_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pause_button.clicked.connect(self._toggle_pause)
        self.cancel_button = QPushButton("لغو")
        self.cancel_button.setObjectName("chip")
        self.cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_button.clicked.connect(lambda: self.session.downloads.cancel(self.item_id))
        self.play_button = QPushButton("پخش در جلوه")
        self.play_button.setObjectName("primary")
        self.play_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.play_button.clicked.connect(self._play)
        self.external_button = QPushButton("پخش‌کننده دیگر")
        self.external_button.setObjectName("chip")
        self.external_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.external_button.clicked.connect(self._open_external)
        self.retry_button = QPushButton("ادامه")
        self.retry_button.setObjectName("primary")
        self.retry_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.retry_button.clicked.connect(lambda: self.session.downloads.resume(self.item_id))
        self.remove_button = QPushButton("حذف")
        self.remove_button.setObjectName("text")
        self.remove_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove_button.clicked.connect(lambda: self.session.downloads.remove(self.item_id))
        for button in (
            self.pause_button,
            self.cancel_button,
            self.play_button,
            self.external_button,
            self.retry_button,
            self.remove_button,
        ):
            actions.addWidget(button)
        actions.addStretch(1)
        layout.addWidget(self.title)
        layout.addWidget(self.detail)
        layout.addWidget(self.bar)
        layout.addWidget(self.meta_host)
        layout.addLayout(actions)
        self.apply(item)

    def apply(self, item: dict) -> None:
        self.item_id = item.get("id") or self.item_id
        self._path = item.get("path") or ""
        self._title = item.get("title") or "دانلود"
        self.title.setText(self._title)
        self.detail.setText(item.get("detail") or "")
        status = item.get("status") or ""
        received = int(item.get("received") or 0)
        total = int(item.get("total") or 0)
        speed = float(item.get("speed") or 0)
        if total > 0:
            percent = max(0, min(100, int(received * 100 / total)))
            self.bar.setRange(0, 100)
            self.bar.setValue(percent)
        elif status in {"downloading", "paused"} and received > 0:
            self.bar.setRange(0, 0)
        else:
            self.bar.setRange(0, 100)
            self.bar.setValue(100 if status == "done" else 0)

        if status == "downloading":
            self.bar.show()
            parts: list[tuple[str, str]] = []
            if total:
                parts.append((f"{int(received * 100 / total)}%", "ltr"))
            parts.extend(self._size_parts(received, total))
            parts.append((format_speed(speed), "ltr"))
            if total > received and speed > 0:
                parts.append(("باقیمانده", "rtl"))
                parts.append((format_eta((total - received) / speed), "ltr"))
            self._show_meta(parts, "muted")
            self.pause_button.setText("توقف")
            self.pause_button.show()
            self.cancel_button.show()
            self.retry_button.hide()
            self.play_button.hide()
            self.external_button.hide()
        elif status == "paused":
            self.bar.show()
            parts = [("متوقف شد", "rtl")]
            if total:
                parts.append((f"{int(received * 100 / total)}%", "ltr"))
            parts.extend(self._size_parts(received, total))
            self._show_meta(parts, "gold")
            self.pause_button.setText("ادامه")
            self.pause_button.show()
            self.cancel_button.show()
            self.retry_button.hide()
            self.play_button.hide()
            self.external_button.hide()
        elif status == "done":
            self.bar.show()
            self.bar.setRange(0, 100)
            self.bar.setValue(100)
            size = Path(self._path).stat().st_size if Path(self._path).is_file() else received or total
            self._show_meta([("آماده پخش", "rtl"), (format_bytes(size), "ltr")], "mint")
            self.pause_button.hide()
            self.cancel_button.hide()
            self.retry_button.hide()
            self.play_button.show()
            self.external_button.show()
        else:
            self.bar.hide()
            self._show_meta([(item.get("error") or "خطا در دانلود", "rtl")], "muted")
            self.pause_button.hide()
            self.cancel_button.hide()
            self.retry_button.show()
            self.play_button.hide()
            self.external_button.hide()

    @staticmethod
    def _size_parts(received: int, total: int) -> list[tuple[str, str]]:
        if total <= 0:
            return [(format_bytes(received), "ltr")]
        return [(format_bytes(received), "ltr"), ("از", "rtl"), (format_bytes(total), "ltr")]

    def _show_meta(self, parts: list[tuple[str, str]], role: str) -> None:
        for index, label in enumerate(self._meta_labels):
            if index >= len(parts):
                label.hide()
                continue
            text, direction = parts[index]
            label.setText(text)
            label.setObjectName(role)
            label.setLayoutDirection(
                Qt.LayoutDirection.LeftToRight if direction == "ltr" else Qt.LayoutDirection.RightToLeft
            )
            label.style().unpolish(label)
            label.style().polish(label)
            label.show()

    def _toggle_pause(self) -> None:
        item = next((entry for entry in self.session.downloads.items if entry.get("id") == self.item_id), None)
        if not item:
            return
        if item.get("status") == "paused":
            self.session.downloads.resume(self.item_id)
        else:
            self.session.downloads.pause(self.item_id)

    def _play(self) -> None:
        self.hub.play_file.emit(self._path, self._title)

    def _open_external(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(self._path))


class LibraryPage(Page):
    def __init__(self, session, hub):
        super().__init__(session, hub)
        self._open_playlist_id: int | None = None
        self._download_rows: dict[str, DownloadRow] = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 18, 28, 12)
        header = QHBoxLayout()
        self.fav_tab = QPushButton("علاقه‌مندی‌ها")
        self.list_tab = QPushButton("پلی‌لیست‌ها")
        self.down_tab = QPushButton("دانلودها")
        for button in (self.fav_tab, self.list_tab, self.down_tab):
            button.setCheckable(True)
            button.setObjectName("chip")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.fav_tab.setChecked(True)
        self.fav_tab.clicked.connect(lambda: self._show_tab("favorites"))
        self.list_tab.clicked.connect(lambda: self._show_tab("playlists"))
        self.down_tab.clicked.connect(lambda: self._show_tab("downloads"))
        header.addWidget(self.fav_tab)
        header.addWidget(self.list_tab)
        header.addWidget(self.down_tab)
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
        self.session.downloads.updated.connect(self._downloads_changed)

    def _downloads_changed(self) -> None:
        if self.mode == "downloads" and self.isVisible():
            self._sync_downloads()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.reload()

    def reload(self) -> None:
        if self.mode == "downloads":
            self._show_downloads()
            return
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
        self.down_tab.setChecked(mode == "downloads")
        self.reload()

    def _show_downloads(self) -> None:
        self.busy.hide()
        self.grid.set_cards([])
        self._clear(self.lists)
        self._download_rows.clear()
        header = QHBoxLayout()
        heading = QLabel("دانلودها")
        heading.setObjectName("section")
        folder = QPushButton("باز کردن پوشه")
        folder.setObjectName("chip")
        folder.setCursor(Qt.CursorShape.PointingHandCursor)
        folder.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.session.downloads.folder)))
        )
        header.addWidget(heading, 1)
        header.addWidget(folder)
        self.lists.addLayout(header)
        note = QLabel("پیشرفت، توقف و ادامه دانلود اینجا دیده می‌شود. فایل‌ها روی همین رایانه ذخیره می‌شوند.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        self.lists.addWidget(note)
        self._downloads_host = QVBoxLayout()
        self._downloads_host.setSpacing(12)
        self.lists.addLayout(self._downloads_host)
        items = self.session.downloads.items
        if not items:
            empty = QLabel("هنوز چیزی دانلود نشده است.")
            empty.setObjectName("muted")
            self._downloads_host.addWidget(empty)
            return
        for item in items:
            row = DownloadRow(item, self.session, self.hub)
            self._download_rows[item["id"]] = row
            self._downloads_host.addWidget(row)

    def _sync_downloads(self) -> None:
        if not hasattr(self, "_downloads_host"):
            self._show_downloads()
            return
        items = self.session.downloads.items
        ids = [item["id"] for item in items if item.get("id")]
        if set(ids) != set(self._download_rows) or len(ids) != len(self._download_rows):
            self._show_downloads()
            return
        for item in items:
            row = self._download_rows.get(item["id"])
            if row:
                row.apply(item)

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
        self._open_playlist_id = None
        self.grid.set_cards([])
        self._clear(self.lists)
        header = QHBoxLayout()
        title = QLabel("پلی‌لیست‌های من")
        title.setObjectName("section")
        create = QPushButton("ساخت پلی‌لیست")
        create.setObjectName("primary")
        create.setCursor(Qt.CursorShape.PointingHandCursor)
        create.clicked.connect(self._create)
        header.addWidget(title, 1)
        header.addWidget(create)
        self.lists.addLayout(header)
        if not playlists:
            empty = QFrame()
            empty.setObjectName("panel")
            empty_layout = QVBoxLayout(empty)
            empty_layout.setContentsMargins(24, 28, 24, 28)
            empty_layout.setSpacing(10)
            empty_title = QLabel("هنوز پلی‌لیستی نساخته‌اید")
            empty_title.setStyleSheet("font-size: 18px; font-weight: 700;")
            empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_note = QLabel("لیست‌های شخصی بسازید و فیلم و سریال‌های مورد علاقه‌تان را آنجا نگه دارید.")
            empty_note.setObjectName("muted")
            empty_note.setWordWrap(True)
            empty_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_action = QPushButton("اولین پلی‌لیست را بسازید")
            empty_action.setObjectName("primary")
            empty_action.setCursor(Qt.CursorShape.PointingHandCursor)
            empty_action.clicked.connect(self._create)
            empty_layout.addWidget(empty_title)
            empty_layout.addWidget(empty_note)
            empty_layout.addWidget(empty_action, alignment=Qt.AlignmentFlag.AlignCenter)
            self.lists.addWidget(empty)
            return
        for playlist in playlists:
            self.lists.addWidget(self._playlist_card(playlist))

    def _playlist_card(self, playlist: dict) -> QFrame:
        card = QFrame()
        card.setObjectName("panel")
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        top = QHBoxLayout()
        name = QLabel(playlist.get("name") or "لیست")
        name.setStyleSheet("font-size: 16px; font-weight: 700;")
        count = QLabel(f"{int(playlist.get('items_count') or 0)} عنوان")
        count.setObjectName("mint")
        top.addWidget(name, 1)
        top.addWidget(count)
        layout.addLayout(top)
        description = (playlist.get("description") or "").strip()
        if description:
            note = QLabel(description)
            note.setObjectName("dim")
            note.setWordWrap(True)
            layout.addWidget(note)
        actions = QHBoxLayout()
        open_button = QPushButton("مشاهده")
        open_button.setObjectName("chip")
        open_button.setCursor(Qt.CursorShape.PointingHandCursor)
        open_button.clicked.connect(lambda _checked=False, playlist_id=playlist["id"]: self._open_playlist(playlist_id))
        rename = QPushButton("ویرایش")
        rename.setObjectName("text")
        rename.setCursor(Qt.CursorShape.PointingHandCursor)
        rename.clicked.connect(lambda _checked=False, playlist=playlist: self._rename(playlist))
        delete = QPushButton("حذف")
        delete.setObjectName("text")
        delete.setCursor(Qt.CursorShape.PointingHandCursor)
        delete.clicked.connect(lambda _checked=False, playlist=playlist: self._delete_playlist(playlist))
        actions.addWidget(open_button)
        actions.addStretch(1)
        actions.addWidget(rename)
        actions.addWidget(delete)
        layout.addLayout(actions)
        return card

    def _create(self) -> None:
        dialog = PlaylistEditorDialog(self, self.session.theme)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name, description = dialog.result_name, dialog.result_description
        self.session.tasks.run(
            lambda: self.session.api.create_playlist(name, description),
            lambda _result: self._created(),
            self.hub.toast.emit,
        )

    def _created(self) -> None:
        self.hub.toast.emit("پلی‌لیست ساخته شد.")
        self._show_tab("playlists")

    def _rename(self, playlist: dict) -> None:
        dialog = PlaylistEditorDialog(
            self,
            self.session.theme,
            title="ویرایش پلی‌لیست",
            name=playlist.get("name") or "",
            description=playlist.get("description") or "",
            submit_label="ذخیره",
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        playlist_id = int(playlist["id"])
        name, description = dialog.result_name, dialog.result_description
        self.session.tasks.run(
            lambda: self.session.api.update_playlist(playlist_id, name, description),
            lambda _result: self._renamed(),
            self.hub.toast.emit,
        )

    def _renamed(self) -> None:
        self.hub.toast.emit("پلی‌لیست به‌روز شد.")
        if self._open_playlist_id:
            self._open_playlist(self._open_playlist_id)
        else:
            self.reload()

    def _delete_playlist(self, playlist: dict) -> None:
        name = playlist.get("name") or "این لیست"
        answer = QMessageBox.question(
            self,
            "حذف پلی‌لیست",
            f"«{name}» حذف شود؟ این کار برگشت‌پذیر نیست.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        playlist_id = int(playlist["id"])
        self.session.tasks.run(
            lambda: self.session.api.delete_playlist(playlist_id),
            lambda _result: self._deleted_playlist(),
            self.hub.toast.emit,
        )

    def _deleted_playlist(self) -> None:
        self.hub.toast.emit("پلی‌لیست حذف شد.")
        self._open_playlist_id = None
        self._show_tab("playlists")

    def _open_playlist(self, playlist_id: int) -> None:
        self._open_playlist_id = int(playlist_id)
        self.track(lambda: self.session.api.playlist(playlist_id), self._render_playlist)

    def _render_playlist(self, playlist: dict) -> None:
        self.busy.hide()
        self._clear(self.lists)
        self._open_playlist_id = int(playlist.get("id") or self._open_playlist_id or 0) or None
        header = QHBoxLayout()
        back = QPushButton("بازگشت")
        back.setObjectName("chip")
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        back.clicked.connect(lambda: self._show_tab("playlists"))
        title_box = QVBoxLayout()
        title_box.setSpacing(4)
        title = QLabel(playlist.get("name") or "")
        title.setObjectName("section")
        title_box.addWidget(title)
        description = (playlist.get("description") or "").strip()
        if description:
            note = QLabel(description)
            note.setObjectName("dim")
            note.setWordWrap(True)
            title_box.addWidget(note)
        items = playlist.get("items") or []
        count = QLabel(f"{len(items)} عنوان")
        count.setObjectName("muted")
        title_box.addWidget(count)
        rename = QPushButton("ویرایش")
        rename.setObjectName("chip")
        rename.setCursor(Qt.CursorShape.PointingHandCursor)
        rename.clicked.connect(lambda _checked=False, playlist=playlist: self._rename(playlist))
        delete = QPushButton("حذف لیست")
        delete.setObjectName("text")
        delete.setCursor(Qt.CursorShape.PointingHandCursor)
        delete.clicked.connect(lambda _checked=False, playlist=playlist: self._delete_playlist(playlist))
        header.addWidget(back)
        header.addLayout(title_box, 1)
        header.addWidget(rename)
        header.addWidget(delete)
        self.lists.addLayout(header)
        cards = []
        for entry in items:
            data = card_from(entry)
            card = PosterCard(data, self.session.images, self.session.theme)
            card.clicked.connect(lambda item: self.hub.open_title.emit(item["type"], int(item["id"])))
            cards.append(card)
        self.grid.set_cards(cards)
        if not cards:
            empty = QLabel("این پلی‌لیست خالی است. از صفحه عنوان، «افزودن به پلی‌لیست» را بزنید.")
            empty.setObjectName("muted")
            empty.setWordWrap(True)
            self.lists.addWidget(empty)

    def _clear(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
            child = item.layout()
            if child:
                self._clear(child)


class AccountPage(Page):
    def __init__(self, session, hub):
        super().__init__(session, hub)
        self.mode = "login"
        self._stats = {"favorites": 0, "playlists": 0, "history": 0, "downloads": 0}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.area, _canvas, self.body = _scroll()
        outer.addWidget(self.area)

        self.profile_panel = QFrame()
        self.profile_panel.setObjectName("panel")
        profile_layout = QVBoxLayout(self.profile_panel)
        profile_layout.setContentsMargins(24, 22, 24, 22)
        profile_layout.setSpacing(18)
        header = QHBoxLayout()
        header.setSpacing(16)
        self.avatar = QLabel()
        self.avatar.setFixedSize(96, 96)
        self.avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        identity = QVBoxLayout()
        identity.setSpacing(4)
        self.display_name = QLabel("پروفایل")
        self.display_name.setObjectName("section")
        self.display_name.setStyleSheet("font-size: 26px;")
        self.contact = QLabel("")
        self.contact.setObjectName("muted")
        self.member_since = QLabel("")
        self.member_since.setObjectName("dim")
        identity.addWidget(self.display_name)
        identity.addWidget(self.contact)
        identity.addWidget(self.member_since)
        identity.addStretch(1)
        header.addWidget(self.avatar)
        header.addLayout(identity, 1)
        profile_layout.addLayout(header)
        self.stats_row = QHBoxLayout()
        self.stats_row.setSpacing(10)
        self.stat_buttons: dict[str, QPushButton] = {}
        for key, label in (
            ("favorites", "علاقه‌مندی‌ها"),
            ("playlists", "پلی‌لیست‌ها"),
            ("history", "ادامه تماشا"),
            ("downloads", "دانلودها"),
        ):
            button = QPushButton(f"0\n{label}")
            button.setObjectName("chip")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setMinimumHeight(72)
            button.clicked.connect(lambda _checked=False, key=key: self._open_library(key))
            self.stat_buttons[key] = button
            self.stats_row.addWidget(button)
        profile_layout.addLayout(self.stats_row)
        self.body.addWidget(self.profile_panel)

        self.settings_panel = QFrame()
        self.settings_panel.setObjectName("panel")
        settings_layout = QVBoxLayout(self.settings_panel)
        settings_layout.setContentsMargins(20, 18, 20, 18)
        settings_layout.setSpacing(12)
        settings_title = QLabel("تنظیمات")
        settings_title.setObjectName("section")
        settings_title.setStyleSheet("font-size: 18px;")
        theme_row = QHBoxLayout()
        theme_label = QLabel("ظاهر برنامه")
        self.theme_button = QPushButton("حالت روشن")
        self.theme_button.setObjectName("chip")
        self.theme_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.theme_button.setIconSize(QSize(18, 18))
        self.theme_button.clicked.connect(self.session.theme.toggle)
        theme_row.addWidget(theme_label, 1)
        theme_row.addWidget(self.theme_button)
        settings_layout.addWidget(settings_title)
        settings_layout.addLayout(theme_row)
        self.body.addWidget(self.settings_panel)

        self.security_panel = QFrame()
        self.security_panel.setObjectName("panel")
        security_layout = QVBoxLayout(self.security_panel)
        security_layout.setContentsMargins(20, 18, 20, 18)
        security_layout.setSpacing(10)
        security_title = QLabel("امنیت حساب")
        security_title.setObjectName("section")
        security_title.setStyleSheet("font-size: 18px;")
        security_hint = QLabel("رمز عبور فعلی را وارد کنید و رمز تازه بسازید.")
        security_hint.setObjectName("muted")
        security_hint.setWordWrap(True)
        self.current_password = QLineEdit()
        self.current_password.setPlaceholderText("رمز فعلی")
        self.current_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.current_password.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.new_password = QLineEdit()
        self.new_password.setPlaceholderText("رمز تازه")
        self.new_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.new_password.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.confirm_password = QLineEdit()
        self.confirm_password.setPlaceholderText("تکرار رمز تازه")
        self.confirm_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm_password.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.change_password_button = QPushButton("تغییر رمز عبور")
        self.change_password_button.setObjectName("primary")
        self.change_password_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.change_password_button.clicked.connect(self._change_password)
        self.confirm_password.returnPressed.connect(self._change_password)
        security_layout.addWidget(security_title)
        security_layout.addWidget(security_hint)
        security_layout.addWidget(self.current_password)
        security_layout.addWidget(self.new_password)
        security_layout.addWidget(self.confirm_password)
        security_layout.addWidget(self.change_password_button, alignment=Qt.AlignmentFlag.AlignLeft)
        self.body.addWidget(self.security_panel)

        self.auth_panel = QFrame()
        self.auth_panel.setObjectName("panel")
        self.auth_panel.setMaximumWidth(480)
        auth_layout = QVBoxLayout(self.auth_panel)
        auth_layout.setContentsMargins(24, 22, 24, 22)
        auth_layout.setSpacing(12)
        self.auth_title = QLabel("ورود به حساب")
        self.auth_title.setObjectName("section")
        self.auth_hint = QLabel("با شماره موبایل وارد شوید تا پخش، علاقه‌مندی و نظرها فعال شود.")
        self.auth_hint.setObjectName("muted")
        self.auth_hint.setWordWrap(True)
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
        self.submit.setCursor(Qt.CursorShape.PointingHandCursor)
        self.submit.clicked.connect(self._submit)
        self.switch = QPushButton("حساب ندارید؟ ثبت‌نام")
        self.switch.setObjectName("text")
        self.switch.setCursor(Qt.CursorShape.PointingHandCursor)
        self.switch.clicked.connect(self._toggle_mode)
        for widget in (
            self.auth_title,
            self.auth_hint,
            self.name,
            self.phone,
            self.password,
            self.submit,
            self.switch,
        ):
            auth_layout.addWidget(widget)
        self.body.addWidget(self.auth_panel)

        self.account_panel = QFrame()
        self.account_panel.setObjectName("panel")
        account_layout = QVBoxLayout(self.account_panel)
        account_layout.setContentsMargins(20, 18, 20, 18)
        account_layout.setSpacing(10)
        account_title = QLabel("حساب کاربری")
        account_title.setObjectName("section")
        account_title.setStyleSheet("font-size: 18px;")
        account_hint = QLabel("خروج فقط این دستگاه را از حساب جدا می‌کند.")
        account_hint.setObjectName("muted")
        account_hint.setWordWrap(True)
        self.logout_button = QPushButton("خروج از حساب")
        self.logout_button.setObjectName("chip")
        self.logout_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.logout_button.clicked.connect(self._logout)
        account_layout.addWidget(account_title)
        account_layout.addWidget(account_hint)
        account_layout.addWidget(self.logout_button, alignment=Qt.AlignmentFlag.AlignLeft)
        self.body.addWidget(self.account_panel)
        self.body.addStretch(1)

        self.session.auth_changed.connect(self.refresh)
        self.session.theme.changed.connect(self._sync_theme_button)
        self.session.history_changed.connect(self._refresh_local_stats)
        self.session.downloads.updated.connect(self._refresh_local_stats)
        self.refresh()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()
        if self.session.user:
            self._load_remote_stats()
            self.session.tasks.run(self.session.api.me, self._me_ok, lambda _message: None)

    def _sync_theme_button(self) -> None:
        dark = self.session.theme.mode == "dark"
        self.theme_button.setText("حالت روشن" if dark else "حالت تاریک")
        color = self.session.theme.palette.gold if dark else self.session.theme.palette.text
        self.theme_button.setIcon(sun_icon(color) if dark else moon_icon(color))

    def _refresh_local_stats(self) -> None:
        self._stats["history"] = len(self.session.history())
        self._stats["downloads"] = len(self.session.downloads.items)
        self._paint_stats()

    def _load_remote_stats(self) -> None:
        def load():
            favorites, _meta = self.session.api.favorites(page=1)
            playlists = self.session.api.playlists()
            return len(favorites or []), len(playlists or [])

        def ok(result):
            favorites, playlists = result
            self._stats["favorites"] = favorites
            self._stats["playlists"] = playlists
            self._paint_stats()

        self.session.tasks.run(load, ok, lambda _message: None)

    def _paint_stats(self) -> None:
        labels = {
            "favorites": "علاقه‌مندی‌ها",
            "playlists": "پلی‌لیست‌ها",
            "history": "ادامه تماشا",
            "downloads": "دانلودها",
        }
        for key, button in self.stat_buttons.items():
            button.setText(f"{self._stats.get(key, 0)}\n{labels[key]}")

    def refresh(self) -> None:
        logged_in = bool(self.session.user)
        self.profile_panel.setVisible(True)
        self.settings_panel.setVisible(True)
        self.security_panel.setVisible(logged_in)
        self.account_panel.setVisible(logged_in)
        self.auth_panel.setVisible(not logged_in)
        for key, button in self.stat_buttons.items():
            button.setEnabled(logged_in or key in ("downloads", "history"))
        self._sync_theme_button()
        self._refresh_local_stats()
        if logged_in:
            user = self.session.user or {}
            name = user.get("name") or "کاربر جلوه"
            contact = user.get("phone") or user.get("email") or ""
            self.display_name.setText(name)
            self.contact.setText(contact)
            self.member_since.setText(self._member_since_text(user.get("created_at")))
            self.avatar.setPixmap(avatar_pixmap(name, 96, self.session.theme.palette.ember))
            self._load_remote_stats()
        else:
            self.display_name.setText("بیننده مهمان")
            self.contact.setText("برای پخش و ذخیره لیست وارد حساب شوید")
            self.member_since.setText("")
            self.avatar.setPixmap(avatar_pixmap("مهمان", 96, self.session.theme.palette.ember))
            self._stats["favorites"] = 0
            self._stats["playlists"] = 0
            self._paint_stats()
            self._apply_mode()

    def _member_since_text(self, value) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        day = text[:10]
        if len(day) == 10 and day[4] == "-":
            return f"عضویت از {day}"
        return f"عضویت از {text}"

    def _me_ok(self, user: dict) -> None:
        if not user:
            return
        token = self.session.api.token
        self.session.set_session({"user": user, "token": token})

    def _toggle_mode(self) -> None:
        self.mode = "register" if self.mode == "login" else "login"
        self._apply_mode()

    def _apply_mode(self) -> None:
        register = self.mode == "register"
        self.auth_title.setText("ثبت‌نام" if register else "ورود به حساب")
        self.submit.setText("ساخت حساب" if register else "ورود")
        self.switch.setText("حساب دارید؟ ورود" if register else "حساب ندارید؟ ثبت‌نام")
        self.name.setVisible(register)
        self.auth_hint.setText(
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
        self.refresh()

    def _failed(self, message: str) -> None:
        self.submit.setEnabled(True)
        self.hub.toast.emit(message)

    def _change_password(self) -> None:
        current = self.current_password.text()
        new = self.new_password.text()
        confirm = self.confirm_password.text()
        if not current or not new:
            self.hub.toast.emit("رمز فعلی و رمز تازه را وارد کنید.")
            return
        if new != confirm:
            self.hub.toast.emit("تکرار رمز تازه یکسان نیست.")
            return
        self.change_password_button.setEnabled(False)
        self.session.tasks.run(
            lambda: self.session.api.change_password(current, new),
            self._password_changed,
            self._password_failed,
        )

    def _password_changed(self, _result) -> None:
        self.change_password_button.setEnabled(True)
        self.current_password.clear()
        self.new_password.clear()
        self.confirm_password.clear()
        self.hub.toast.emit("رمز عبور تغییر کرد.")

    def _password_failed(self, message: str) -> None:
        self.change_password_button.setEnabled(True)
        self.hub.toast.emit(message)

    def _logout(self) -> None:
        answer = QMessageBox.question(
            self,
            "خروج از حساب",
            "از حساب خارج می‌شوید؟",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.session.logout()

    def _open_library(self, key: str) -> None:
        if key == "history":
            self.hub.navigate.emit("home")
            return
        self.hub.navigate.emit("library")
        window = self.window()
        tab = {"favorites": "favorites", "playlists": "playlists", "downloads": "downloads"}.get(key, "favorites")
        if hasattr(window, "library"):
            QTimer.singleShot(60, lambda tab=tab: window.library._show_tab(tab))
