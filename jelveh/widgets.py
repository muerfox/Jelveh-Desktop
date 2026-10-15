"""Shared poster, row, hero, and overlay widgets."""

from __future__ import annotations

import math

from PySide6.QtCore import QEasingCurve, Property, QPoint, QPropertyAnimation, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .images import cover_pixmap


def rating_text(item: dict) -> str:
    value = item.get("rating", item.get("imdb_score"))
    if value in (None, ""):
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if number <= 0:
        return ""
    return f"{number:.1f}"


def card_from(item: dict, kind: str | None = None) -> dict:
    nested = item.get("item") if isinstance(item.get("item"), dict) else None
    source = nested or item
    return {
        "id": source.get("id"),
        "type": source.get("type") or kind or "movie",
        "title": source.get("title") or source.get("name") or "",
        "poster": source.get("poster"),
        "backdrop": source.get("backdrop") or source.get("poster"),
        "rating": source.get("rating", source.get("imdb_score")),
        "year": source.get("release_year"),
        "overview": source.get("overview") or "",
        "favorite_id": item.get("id") if nested else None,
        "playlist_item_id": item.get("id") if nested and "added_at" in item else None,
    }


class Spinner(QWidget):
    def __init__(self, parent=None, size: int = 36):
        super().__init__(parent)
        self._angle = 0
        self._size = size
        self.setFixedSize(size, size)
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    def showEvent(self, event) -> None:
        self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def _tick(self) -> None:
        self._angle = (self._angle + 8) % 360
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("#e50914"))
        pen.setWidth(3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        rect = QRectF(4, 4, self._size - 8, self._size - 8)
        painter.drawArc(rect, int((-self._angle) * 16), 110 * 16)
        painter.end()


class BusyOverlay(QWidget):
    def __init__(self, parent, theme):
        super().__init__(parent)
        self.theme = theme
        self.theme.changed.connect(self.update)
        layout = QVBoxLayout(self)
        layout.addStretch(1)
        self.spinner = Spinner()
        layout.addWidget(self.spinner, alignment=Qt.AlignmentFlag.AlignCenter)
        self.label = QLabel("در حال بارگذاری…")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.label)
        layout.addStretch(1)
        self.hide()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        color = QColor(self.theme.palette.bg)
        color.setAlpha(150)
        painter.fillRect(self.rect(), color)
        painter.end()

    def reposition(self) -> None:
        if self.parentWidget():
            self.setGeometry(self.parentWidget().rect())
            self.raise_()


class PosterCard(QFrame):
    clicked = Signal(object)

    def __init__(self, item: dict, images, theme, parent=None):
        super().__init__(parent)
        self.item = item
        self.images = images
        self.theme = theme
        self._hover = 0.0
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedWidth(156)
        self.setObjectName("poster")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.art = QLabel()
        self.art.setFixedSize(156, 234)
        self.art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.art)
        self.badge = QLabel(self.art)
        self.badge.setObjectName("gold")
        score = rating_text(item)
        self.badge.setText(score)
        self.badge.setVisible(bool(score))
        self.badge.setStyleSheet(
            "background: rgba(0,0,0,0.72); color: #ffc857; border-radius: 8px; padding: 2px 6px; font-weight: 700;"
        )
        self.badge.adjustSize()
        self.badge.move(156 - self.badge.width() - 8, 8)
        self.caption = QLabel(item.get("title") or "")
        self.caption.setWordWrap(True)
        self.caption.setFixedHeight(40)
        self.caption.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.caption)
        self._anim = QPropertyAnimation(self, b"hover", self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.theme.changed.connect(self._paint_placeholder)
        self._paint_placeholder()
        poster = item.get("poster")
        if poster:
            self.images.load(poster, self._set_image)

    def get_hover(self) -> float:
        return self._hover

    def set_hover(self, value: float) -> None:
        self._hover = value
        margin = int(4 * (1 - value))
        self.layout().setContentsMargins(0, margin, 0, int(4 * value))
        self._restyle()

    hover = Property(float, get_hover, set_hover)

    def _restyle(self) -> None:
        ember = self.theme.palette.ember if self._hover > 0.4 else "transparent"
        self.art.setStyleSheet(f"border-radius: 14px; border: 2px solid {ember};")

    def _paint_placeholder(self) -> None:
        self._restyle()
        pix = QPixmap(156, 234)
        pix.fill(QColor(self.theme.palette.card))
        painter = QPainter(pix)
        painter.setPen(QColor(self.theme.palette.muted))
        font = QFont(self.theme.family)
        font.setPixelSize(28)
        font.setWeight(QFont.Weight.Bold)
        painter.setFont(font)
        letter = (self.item.get("title") or "ج")[:1]
        painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, letter)
        painter.end()
        self.art.setPixmap(pix)

    def _set_image(self, image) -> None:
        from shiboken6 import isValid

        if image is None or not isValid(self.art):
            return
        self.art.setPixmap(cover_pixmap(image, 156, 234, 14))
        self.badge.raise_()

    def enterEvent(self, event) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._hover)
        self._anim.setEndValue(1.0)
        self._anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._hover)
        self._anim.setEndValue(0.0)
        self._anim.start()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.item)
        super().mouseReleaseEvent(event)


class SmoothScroll(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._anim = QPropertyAnimation(self.horizontalScrollBar(), b"value", self)
        self._anim.setDuration(280)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y() or event.angleDelta().x()
        self.nudge(-delta)

    def nudge(self, amount: int) -> None:
        bar = self.horizontalScrollBar()
        self._anim.stop()
        start = bar.value()
        end = max(bar.minimum(), min(bar.maximum(), start + amount))
        self._anim.setStartValue(start)
        self._anim.setEndValue(end)
        self._anim.start()


class PosterRow(QWidget):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(10)
        header = QHBoxLayout()
        self.heading = QLabel(title)
        self.heading.setObjectName("section")
        header.addWidget(self.heading)
        header.addStretch(1)
        self.prev = QPushButton("›")
        self.next = QPushButton("‹")
        for button in (self.prev, self.next):
            button.setFixedSize(32, 32)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        header.addWidget(self.prev)
        header.addWidget(self.next)
        layout.addLayout(header)
        self.scroll = SmoothScroll()
        self.scroll.setFixedHeight(292)
        self.inner = QWidget()
        self.inner.setObjectName("canvas")
        self.row = QHBoxLayout(self.inner)
        self.row.setContentsMargins(2, 2, 2, 2)
        self.row.setSpacing(14)
        self.row.addStretch(1)
        self.scroll.setWidget(self.inner)
        layout.addWidget(self.scroll)
        self.prev.clicked.connect(lambda: self.scroll.nudge(-480))
        self.next.clicked.connect(lambda: self.scroll.nudge(480))

    def set_cards(self, cards: list[PosterCard]) -> None:
        while self.row.count():
            item = self.row.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        for card in cards:
            self.row.addWidget(card)
        self.row.addStretch(1)


class Hero(QWidget):
    play_clicked = Signal(object)
    info_clicked = Signal(object)

    def __init__(self, images, theme, parent=None):
        super().__init__(parent)
        self.images = images
        self.theme = theme
        self.slides: list[dict] = []
        self.index = 0
        self.setMinimumHeight(420)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(440)
        self.backdrop = QLabel(self)
        self.backdrop.setScaledContents(False)
        self.shade = QWidget(self)
        self.shade.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.title = QLabel(self)
        self.title.setObjectName("heroTitle")
        self.title.setWordWrap(True)
        self.meta = QLabel(self)
        self.meta.setObjectName("heroMeta")
        self.overview = QLabel(self)
        self.overview.setObjectName("heroOverview")
        self.overview.setWordWrap(True)
        self.play = QPushButton("پخش", self)
        self.play.setObjectName("primary")
        self.play.setCursor(Qt.CursorShape.PointingHandCursor)
        self.info = QPushButton("جزئیات", self)
        self.info.setObjectName("ghost")
        self.info.setCursor(Qt.CursorShape.PointingHandCursor)
        self.play.clicked.connect(lambda: self.slides and self.play_clicked.emit(self.slides[self.index]))
        self.info.clicked.connect(lambda: self.slides and self.info_clicked.emit(self.slides[self.index]))
        self.dots: list[QPushButton] = []
        self.timer = QTimer(self)
        self.timer.setInterval(7000)
        self.timer.timeout.connect(self.next)
        self._image = None
        self.theme.changed.connect(self.update)

    def set_slides(self, slides: list[dict]) -> None:
        self.slides = [slide for slide in slides if slide.get("id")]
        self.index = 0
        for dot in self.dots:
            dot.deleteLater()
        self.dots = []
        for position, _slide in enumerate(self.slides[:8]):
            dot = QPushButton(self)
            dot.setFixedSize(22, 6)
            dot.setCursor(Qt.CursorShape.PointingHandCursor)
            dot.clicked.connect(lambda _checked=False, position=position: self.show_index(position))
            self.dots.append(dot)
        self.slides = self.slides[:8]
        self.setVisible(bool(self.slides))
        if self.slides:
            self.show_index(0)
            if len(self.slides) > 1:
                self.timer.start()
        self.update()

    def show_index(self, index: int) -> None:
        if not self.slides:
            return
        self.index = index % len(self.slides)
        slide = self.slides[self.index]
        self.title.setText(slide.get("title") or "")
        bits = []
        if slide.get("year"):
            bits.append(str(slide["year"]))
        score = rating_text(slide)
        if score:
            bits.append(score)
        kind = "سریال" if slide.get("type") == "series" else "فیلم"
        bits.append(kind)
        self.meta.setText("  ·  ".join(bits))
        text = (slide.get("overview") or "").strip()
        self.overview.setText(text[:180] + ("…" if len(text) > 180 else ""))
        self.overview.setVisible(bool(text))
        image_url = slide.get("backdrop") or slide.get("poster")
        self.images.load(image_url, self._set_backdrop)
        self._layout_dots()
        self.update()

    def next(self) -> None:
        if self.slides:
            self.show_index(self.index + 1)

    def update_slide(self, title_id: int, fields: dict) -> None:
        for slide in self.slides:
            if slide.get("id") == title_id:
                slide.update(fields)
        if self.slides and self.slides[self.index].get("id") == title_id:
            self.show_index(self.index)

    def _set_backdrop(self, image) -> None:
        from shiboken6 import isValid

        if not isValid(self):
            return
        self._image = image
        self._paint_backdrop()

    def _paint_backdrop(self) -> None:
        self.backdrop.setPixmap(cover_pixmap(self._image, max(self.width(), 10), max(self.height(), 10), 0))
        self.backdrop.setGeometry(self.rect())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.backdrop.setGeometry(self.rect())
        self.shade.setGeometry(self.rect())
        self._paint_backdrop()
        width = min(560, self.width() - 80)
        right = 36
        self.title.setGeometry(self.width() - width - right, 150, width, 90)
        self.meta.setGeometry(self.width() - width - right, 244, width, 28)
        self.overview.setGeometry(self.width() - width - right, 276, width, 72)
        self.play.setGeometry(self.width() - 140 - right, 360, 120, 42)
        self.info.setGeometry(self.width() - 270 - right, 360, 120, 42)
        self._layout_dots()

    def _layout_dots(self) -> None:
        total = len(self.dots) * 28
        x = (self.width() - total) // 2
        for position, dot in enumerate(self.dots):
            active = position == self.index
            dot.setStyleSheet(
                f"background: {'#e50914' if active else 'rgba(255,255,255,0.45)'}; border-radius: 3px; border: none;"
            )
            dot.setGeometry(x + position * 28, self.height() - 22, 18, 6)
            dot.raise_()
        for widget in (self.title, self.meta, self.overview, self.play, self.info):
            widget.raise_()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(0, 0, -1, -1), 22, 22)
        painter.setClipPath(path)
        painter.fillRect(self.rect(), QColor("#111111"))
        fade = QColor(self.theme.palette.hero_fade)
        gradient_rect = self.rect()
        painter.fillRect(gradient_rect, QColor(0, 0, 0, 0))
        for step in range(12):
            alpha = int(210 * (step / 12) ** 1.4)
            band = QColor(fade)
            band.setAlpha(alpha)
            y = self.height() - int(self.height() * 0.55) + int(self.height() * 0.55 * step / 12)
            painter.fillRect(0, y, self.width(), int(self.height() * 0.55 / 12) + 2, band)
        side = QColor(0, 0, 0, 90)
        painter.fillRect(self.width() // 2, 0, self.width() // 2, self.height(), side)
        painter.end()

    def enterEvent(self, event) -> None:
        self.timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        if len(self.slides) > 1:
            self.timer.start()
        super().leaveEvent(event)


class FlowGrid(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.cards: list[QWidget] = []
        self.setObjectName("canvas")

    def set_cards(self, cards: list[QWidget], append: bool = False) -> None:
        if not append:
            for card in self.cards:
                card.setParent(None)
                card.deleteLater()
            self.cards = []
        self.cards.extend(cards)
        self.relayout()

    def relayout(self) -> None:
        width = max(self.width(), 320)
        columns = max(2, width // 176)
        for index, card in enumerate(self.cards):
            row, column = divmod(index, columns)
            card.setParent(self)
            card.move(width - (column + 1) * 170 - 8, 8 + row * 300)
            card.show()
        rows = math.ceil(len(self.cards) / columns) if self.cards else 0
        self.setMinimumHeight(rows * 300 + 16)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.relayout()


class Toast(QLabel):
    def __init__(self, parent, theme):
        super().__init__(parent)
        self.theme = theme
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self.theme.changed.connect(self._restyle)
        self._restyle()

    def _restyle(self) -> None:
        c = self.theme.palette
        self.setStyleSheet(
            f"background: {c.card}; color: {c.text}; border: 1px solid {c.line}; "
            "border-radius: 14px; padding: 10px 16px; font-weight: 600;"
        )

    def show_message(self, text: str) -> None:
        self.setText(text)
        self.adjustSize()
        self.setFixedHeight(max(42, self.sizeHint().height()))
        parent = self.parentWidget()
        if parent:
            self.move(max(16, (parent.width() - self.width()) // 2), parent.height() - 72)
        self.raise_()
        self.show()
        self._timer.start(3200)
