"""Shared poster, row, hero, and overlay widgets."""

from __future__ import annotations

import math
from collections import OrderedDict

from PySide6.QtCore import QEasingCurve, Property, QPoint, QPropertyAnimation, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QGraphicsBlurEffect,
    QGraphicsDropShadowEffect,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .images import cover_pixmap
from .theme import rating_chip_pixmap


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


class CompactCombo(QComboBox):
    """Short field. The list opens at its final size and scrolls smoothly."""

    def __init__(self, parent=None, visible: int = 8):
        super().__init__(parent)
        self._visible = visible
        self.setMaxVisibleItems(visible)
        view = self.view()
        view.setUniformItemSizes(True)
        view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        view.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        view.setFrameShape(QFrame.Shape.NoFrame)
        view.setSpacing(2)
        bar = view.verticalScrollBar()
        bar.setSingleStep(14)

    def showPopup(self) -> None:
        view = self.view()
        rows = min(self._visible, max(self.count(), 1))
        row_height = view.sizeHintForRow(0)
        if row_height < 28:
            row_height = self.fontMetrics().height() + 16
        height = row_height * rows + view.spacing() * 2 + 6
        # Lock the size before the popup appears so it does not jump open.
        view.setMinimumHeight(height)
        view.setMaximumHeight(height)
        super().showPopup()
        popup = view.window()
        if popup is not None and popup is not self.window():
            popup.setFixedWidth(max(self.width(), popup.width()))

    def hidePopup(self) -> None:
        view = self.view()
        view.setMinimumHeight(0)
        view.setMaximumHeight(16777215)
        super().hidePopup()


class PosterCard(QFrame):
    clicked = Signal(object)

    def __init__(self, item: dict, images, theme, parent=None):
        super().__init__(parent)
        self.item = item
        self.images = images
        self.theme = theme
        self._hover = 0.0
        self._image = None
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
        self.badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        score = rating_text(item)
        if score:
            chip = rating_chip_pixmap(score)
            self.badge.setPixmap(chip)
            self.badge.setFixedSize(chip.size())
            self.badge.move(156 - chip.width() - 8, 8)
            self.badge.show()
        else:
            self.badge.hide()
        self.caption = QLabel(item.get("title") or "")
        self.caption.setWordWrap(True)
        self.caption.setFixedHeight(40)
        self.caption.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.caption)
        self._anim = QPropertyAnimation(self, b"hover", self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.theme.changed.connect(self._on_theme)
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

    def _on_theme(self) -> None:
        self._restyle()
        if self._image is not None and not self._image.isNull():
            self._apply_image(self._image)
        else:
            self._paint_placeholder()

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

        if image is None or image.isNull() or not isValid(self.art):
            return
        self._image = image
        self._apply_image(image)

    def _apply_image(self, image) -> None:
        self.art.setPixmap(cover_pixmap(image, 156, 234, 22))
        self.badge.raise_()

    def enterEvent(self, event) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._hover)
        self._anim.setEndValue(1.0)
        self._anim.start()
        window = self.window()
        show = getattr(window, "show_ambient", None)
        if show is not None:
            show(self.item.get("backdrop") or self.item.get("poster"))
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._hover)
        self._anim.setEndValue(0.0)
        self._anim.start()
        window = self.window()
        hide = getattr(window, "hide_ambient", None)
        if hide is not None:
            hide()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and not _row_was_dragged(self):
            self.clicked.emit(self.item)
        super().mouseReleaseEvent(event)


def _row_was_dragged(widget: QWidget) -> bool:
    current = widget.parentWidget()
    while current is not None:
        if isinstance(current, SmoothScroll) and current.dragged:
            return True
        current = current.parentWidget()
    return False


class SmoothScroll(QScrollArea):
    """Horizontal carousel: drag to move, never steal the page wheel scroll."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
        self.viewport().setAutoFillBackground(False)
        self._press = None
        self._origin = 0
        self.dragged = False
        self.viewport().installEventFilter(self)

    def wheelEvent(self, event) -> None:
        # Vertical page scroll only — do not swipe the row with the mouse wheel.
        event.ignore()

    def eventFilter(self, watched, event) -> bool:
        if watched is not self.viewport():
            return super().eventFilter(watched, event)
        etype = event.type()
        if etype == event.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            self._press = event.position().toPoint()
            self._origin = self.horizontalScrollBar().value()
            self.dragged = False
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            return False
        if etype == event.Type.MouseMove and self._press is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.position().toPoint() - self._press
            if abs(delta.x()) > 6 or abs(delta.y()) > 6:
                self.dragged = True
            if self.dragged:
                # Content follows the pointer (grab-and-drag).
                self.horizontalScrollBar().setValue(self._origin + delta.x())
                return True
            return False
        if etype == event.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            was_drag = self.dragged
            self._press = None
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
            if was_drag:
                QTimer.singleShot(0, self._clear_drag)
                return True
            return False
        return super().eventFilter(watched, event)

    def _clear_drag(self) -> None:
        self.dragged = False


class PosterRow(QWidget):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(10)
        self.heading = QLabel(title)
        self.heading.setObjectName("section")
        layout.addWidget(self.heading)
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
        self.setFixedHeight(460)
        self.poster = QLabel(self)
        self.poster.setFixedSize(186, 278)
        self.poster.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        shadow = QGraphicsDropShadowEffect(self.poster)
        shadow.setBlurRadius(32)
        shadow.setOffset(0, 12)
        shadow.setColor(QColor(0, 0, 0, 170))
        self.poster.setGraphicsEffect(shadow)
        self._paint_poster(None)

        self.panel = QWidget(self)
        self.panel.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        column = QVBoxLayout(self.panel)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(10)
        column.addStretch(1)

        self.title = QLabel()
        self.title.setObjectName("heroTitle")
        self.title.setWordWrap(True)
        self.title.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute | Qt.AlignmentFlag.AlignBottom)
        self.title.setStyleSheet(
            "color: #ffffff; font-size: 36px; font-weight: 800; background: transparent;"
        )

        self.rating = QLabel()
        self.rating.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.meta = QLabel()
        self.meta.setObjectName("heroMeta")
        self.meta.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute | Qt.AlignmentFlag.AlignVCenter)
        self.meta.setStyleSheet("color: #f2f2f2; background: transparent; font-size: 14px;")
        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(0, 0, 0, 0)
        meta_row.setSpacing(10)
        # Keep the IMDb chip beside the year/kind text, toward the poster — not stranded.
        meta_row.addWidget(self.meta, 0, Qt.AlignmentFlag.AlignVCenter)
        meta_row.addWidget(self.rating, 0, Qt.AlignmentFlag.AlignVCenter)
        meta_row.addStretch(1)

        self.overview = QLabel()
        self.overview.setObjectName("heroOverview")
        self.overview.setWordWrap(True)
        self.overview.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute | Qt.AlignmentFlag.AlignTop)
        self.overview.setStyleSheet("color: #e8e8e8; background: transparent; font-size: 13px;")
        self.overview.setMaximumHeight(72)

        self.play = QPushButton("پخش")
        self.play.setObjectName("primary")
        self.play.setCursor(Qt.CursorShape.PointingHandCursor)
        self.play.setMinimumWidth(104)
        self.info = QPushButton("جزئیات")
        self.info.setObjectName("ghost")
        self.info.setCursor(Qt.CursorShape.PointingHandCursor)
        self.info.setMinimumWidth(104)
        self.play.clicked.connect(lambda: self.slides and self.play_clicked.emit(self.slides[self.index]))
        self.info.clicked.connect(lambda: self.slides and self.info_clicked.emit(self.slides[self.index]))
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 4, 0, 0)
        buttons.setSpacing(10)
        buttons.addStretch(1)
        buttons.addWidget(self.info)
        buttons.addWidget(self.play)

        column.addWidget(self.title)
        column.addLayout(meta_row)
        column.addWidget(self.overview)
        column.addLayout(buttons)

        self.dots: list[QPushButton] = []
        self.timer = QTimer(self)
        self.timer.setInterval(7000)
        self.timer.timeout.connect(self.next)
        self._image = None
        self._poster_image = None
        self._backdrop = QPixmap()
        self._backdrop_key = (0, 0, 0)
        self._token = None
        self._press_global = None
        self._dragged = False
        self._blur_timer = QTimer(self)
        self._blur_timer.setSingleShot(True)
        self._blur_timer.timeout.connect(self._render_backdrop)
        self.setMouseTracking(True)
        for widget in (self, self.panel, self.poster, self.title, self.meta, self.overview, self.rating):
            widget.setMouseTracking(True)
            widget.installEventFilter(self)
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
            dot.clicked.connect(lambda _checked=False, position=position: self._jump(position))
            self.dots.append(dot)
        self.slides = self.slides[:8]
        self.setCursor(Qt.CursorShape.OpenHandCursor if len(self.slides) > 1 else Qt.CursorShape.ArrowCursor)
        self.setVisible(bool(self.slides))
        if self.slides:
            self.show_index(0)
            self._arm_timer()
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
        kind = "سریال" if slide.get("type") == "series" else "فیلم"
        bits.append(kind)
        self.meta.setText("  ·  ".join(bits))
        score = rating_text(slide)
        if score:
            self.rating.setPixmap(rating_chip_pixmap(score))
            self.rating.adjustSize()
            self.rating.show()
        else:
            self.rating.clear()
            self.rating.hide()
        text = (slide.get("overview") or "").strip()
        self.overview.setText(text[:220] + ("…" if len(text) > 220 else ""))
        self.overview.setVisible(bool(text))
        token = (slide.get("id"), self.index)
        self._token = token

        def backdrop(image, token=token):
            if token != self._token:
                return
            self._set_backdrop(image)

        def poster(image, token=token):
            if token != self._token:
                return
            self._set_poster(image)

        self.images.load(slide.get("backdrop") or slide.get("poster"), backdrop)
        self.images.load(slide.get("poster") or slide.get("backdrop"), poster)
        self._layout_chrome()
        self.update()

    def _jump(self, position: int) -> None:
        self.show_index(position)
        self._arm_timer()

    def previous(self) -> None:
        if len(self.slides) > 1:
            self.show_index(self.index - 1)
            self._arm_timer()

    def next(self) -> None:
        if len(self.slides) > 1:
            self.show_index(self.index + 1)
            self._arm_timer()

    def _arm_timer(self) -> None:
        if len(self.slides) > 1 and not self.underMouse():
            self.timer.start()
        else:
            self.timer.stop()

    def eventFilter(self, watched, event) -> bool:
        if watched in (self.play, self.info) or watched in self.dots:
            return super().eventFilter(watched, event)
        etype = event.type()
        if etype == event.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            if len(self.slides) > 1:
                local = event.position().toPoint() if hasattr(event, "position") else event.pos()
                self._press_global = watched.mapToGlobal(local) if watched is not self else self.mapToGlobal(local)
                self._dragged = False
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return False
        if (
            etype == event.Type.MouseMove
            and self._press_global is not None
            and event.buttons() & Qt.MouseButton.LeftButton
            and len(self.slides) > 1
        ):
            local = event.position().toPoint() if hasattr(event, "position") else event.pos()
            current = watched.mapToGlobal(local) if watched is not self else self.mapToGlobal(local)
            delta = current - self._press_global
            if abs(delta.x()) > 10 and abs(delta.x()) >= abs(delta.y()):
                self._dragged = True
            return self._dragged
        if etype == event.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            if self._dragged and self._press_global is not None and len(self.slides) > 1:
                local = event.position().toPoint() if hasattr(event, "position") else event.pos()
                current = watched.mapToGlobal(local) if watched is not self else self.mapToGlobal(local)
                delta = current - self._press_global
                if abs(delta.x()) >= 56 and abs(delta.x()) >= abs(delta.y()):
                    # Content follows the hand: drag right → previous, drag left → next.
                    if delta.x() > 0:
                        self.previous()
                    else:
                        self.next()
                self._press_global = None
                self._dragged = False
                self.setCursor(Qt.CursorShape.OpenHandCursor if len(self.slides) > 1 else Qt.CursorShape.ArrowCursor)
                return True
            self._press_global = None
            self._dragged = False
            self.setCursor(Qt.CursorShape.OpenHandCursor if len(self.slides) > 1 else Qt.CursorShape.ArrowCursor)
            return False
        return super().eventFilter(watched, event)

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
        self._backdrop_key = (0, 0, 0)
        self._render_backdrop()

    def _set_poster(self, image) -> None:
        from shiboken6 import isValid

        if not isValid(self):
            return
        self._poster_image = image
        self._paint_poster(image)

    def _paint_poster(self, image) -> None:
        width, height, radius = 186, 278, 22
        pixmap = cover_pixmap(image, width, height, radius)
        if image is None or image.isNull():
            pixmap = QPixmap(width, height)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#181818"))
            painter.drawRoundedRect(QRectF(0, 0, width, height), radius, radius)
            painter.end()
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(255, 255, 255, 56))
        pen.setWidthF(1.5)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(1, 1, width - 2, height - 2), radius, radius)
        painter.end()
        self.poster.setPixmap(pixmap)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._blur_timer.start(40)
        self._layout_chrome()

    def _render_backdrop(self) -> None:
        key = (self.width(), self.height(), id(self._image) if self._image is not None else 0)
        if key[0] < 20 or key == self._backdrop_key:
            return
        self._backdrop = blurred_cover(self._image, key[0], key[1], 18)
        self._backdrop_key = key
        self.update()

    def _layout_chrome(self) -> None:
        poster_w, poster_h = 186, 278
        margin = 28
        self.poster.setGeometry(margin, self.height() - poster_h - 36, poster_w, poster_h)
        gap = 28
        panel_left = margin + poster_w + gap
        panel_right = 32
        panel_width = max(260, self.width() - panel_left - panel_right)
        panel_top = 48
        panel_height = max(200, self.height() - panel_top - 36)
        self.panel.setGeometry(panel_left, panel_top, panel_width, panel_height)
        self._layout_dots()

    def _layout_dots(self) -> None:
        if not self.dots:
            return
        spacing = 10
        widths = [28 if position == self.index else 10 for position in range(len(self.dots))]
        total = sum(widths) + spacing * (len(self.dots) - 1)
        x = (self.width() - total) // 2
        y = self.height() - 28
        for position, dot in enumerate(self.dots):
            active = position == self.index
            width = widths[position]
            dot.setFixedSize(width, 8)
            dot.setStyleSheet(
                "border: none; border-radius: 4px; "
                f"background: {'#e50914' if active else 'rgba(255,255,255,0.40)'};"
            )
            dot.setGeometry(x, y, width, 8)
            dot.raise_()
            x += width + spacing
        self.poster.raise_()
        self.panel.raise_()
        for dot in self.dots:
            dot.raise_()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(0, 0, -1, -1), 36, 36)
        painter.setClipPath(path)
        if self._backdrop.isNull():
            painter.fillRect(self.rect(), QColor("#111111"))
        else:
            painter.drawPixmap(0, 0, self._backdrop)
        fade = QColor("#050505")
        vertical = QLinearGradient(0, 0, 0, self.height())
        top = QColor(fade)
        top.setAlpha(40)
        mid = QColor(fade)
        mid.setAlpha(110)
        bottom = QColor(fade)
        bottom.setAlpha(235)
        vertical.setColorAt(0, top)
        vertical.setColorAt(0.4, mid)
        vertical.setColorAt(1, bottom)
        painter.fillRect(self.rect(), vertical)
        # Darken the text side (right) so the title block sits on a solid stage.
        side = QLinearGradient(0, 0, self.width(), 0)
        clear = QColor(fade)
        clear.setAlpha(30)
        soft = QColor(fade)
        soft.setAlpha(100)
        strong = QColor(fade)
        strong.setAlpha(210)
        side.setColorAt(0, clear)
        side.setColorAt(0.35, soft)
        side.setColorAt(1, strong)
        painter.fillRect(self.rect(), side)
        painter.end()

    def enterEvent(self, event) -> None:
        self.timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        if len(self.slides) > 1:
            self.timer.start()
        super().leaveEvent(event)


def blurred_cover(image, width: int, height: int, radius: int = 16, fast: bool = False) -> QPixmap:
    """Cover-crop, then blur, keeping a sharp center so the edges stay filled."""
    width = max(int(width), 1)
    height = max(int(height), 1)
    if image is None or image.isNull():
        empty = QPixmap(width, height)
        empty.fill(QColor("#050505"))
        return empty
    pad = radius * 2
    source = cover_pixmap(image, width + pad * 2, height + pad * 2, 0)
    scene = QGraphicsScene()
    item = QGraphicsPixmapItem(source)
    effect = QGraphicsBlurEffect()
    effect.setBlurRadius(radius)
    hint = QGraphicsBlurEffect.BlurHint.PerformanceHint if fast else QGraphicsBlurEffect.BlurHint.QualityHint
    effect.setBlurHints(hint)
    item.setGraphicsEffect(effect)
    scene.addItem(item)
    result = QPixmap(width, height)
    result.fill(QColor("#050505"))
    painter = QPainter(result)
    scene.render(painter, QRectF(0, 0, width, height), QRectF(pad, pad, width, height))
    painter.end()
    return result


def soft_backdrop(image) -> QPixmap:
    """Small, heavily blurred cover. Scaled up later so a hover stays cheap."""
    return blurred_cover(image, 640, 360, 32, fast=True)


class AmbientBackdrop(QWidget):
    """Darkened blur that fades in behind the pages while a title is hovered."""

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self._cache: OrderedDict[str, QPixmap] = OrderedDict()
        self._url = ""
        self._token = 0
        self._base = QPixmap()
        self._old = QPixmap()
        self._scaled = QPixmap()
        self._old_scaled = QPixmap()
        self._scaled_size = QSize()
        self._opacity = 0.0
        self._mix = 1.0
        self._pending = ""
        self._anim = QPropertyAnimation(self, b"opacity", self)
        self._anim.setDuration(320)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._mix_anim = QPropertyAnimation(self, b"mix", self)
        self._mix_anim.setDuration(280)
        self._mix_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._show_timer = QTimer(self)
        self._show_timer.setSingleShot(True)
        self._show_timer.setInterval(60)
        self._show_timer.timeout.connect(self._commit)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(140)
        self._hide_timer.timeout.connect(self._fade_out)
        self.theme.changed.connect(self._refresh)
        self.hide()

    def _refresh(self) -> None:
        host = self.parentWidget()
        if host is not None:
            host.update()

    def get_opacity(self) -> float:
        return self._opacity

    def set_opacity(self, value: float) -> None:
        self._opacity = value
        self._refresh()

    def get_mix(self) -> float:
        return self._mix

    def set_mix(self, value: float) -> None:
        self._mix = value
        self._refresh()

    opacity = Property(float, get_opacity, set_opacity)
    mix = Property(float, get_mix, set_mix)

    def preview(self, url: str | None) -> None:
        self._hide_timer.stop()
        self._pending = url or ""
        if not self._pending:
            self._fade_out()
            return
        self._show_timer.start()

    def dismiss(self) -> None:
        self._show_timer.stop()
        self._hide_timer.start()

    def _commit(self) -> None:
        url = self._pending
        if not url:
            self._fade_out()
            return
        if url == self._url and not self._base.isNull():
            self._fade_in()
            return
        self._url = url
        self._token += 1
        token = self._token
        cached = self._cache.get(url)
        if cached is not None:
            self._cache.move_to_end(url)
            self._apply(cached)
            return
        images = getattr(self.window(), "session", None)
        images = getattr(images, "images", None)
        if images is None:
            return
        images.load(url, lambda image, token=token, url=url: self._loaded(token, url, image))

    def _loaded(self, token: int, url: str, image) -> None:
        from shiboken6 import isValid

        if token != self._token or not isValid(self):
            return
        if image is None or image.isNull():
            return
        pixmap = soft_backdrop(image)
        self._cache[url] = pixmap
        while len(self._cache) > 16:
            self._cache.popitem(last=False)
        if url == self._url:
            self._apply(pixmap)

    def _apply(self, pixmap: QPixmap) -> None:
        if not self._base.isNull() and self._opacity > 0.15:
            self._old = self._base
            self._old_scaled = self._scaled
            self._mix = 0.0
            self._mix_anim.stop()
            self._mix_anim.setStartValue(0.0)
            self._mix_anim.setEndValue(1.0)
            self._mix_anim.start()
        else:
            self._old = QPixmap()
            self._old_scaled = QPixmap()
            self._mix = 1.0
        self._base = pixmap
        self._scaled = QPixmap()
        self._scaled_size = QSize()
        self._fade_in()

    def _fade_in(self) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._opacity)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def _fade_out(self) -> None:
        self._pending = ""
        self._anim.stop()
        self._anim.setStartValue(self._opacity)
        self._anim.setEndValue(0.0)
        self._anim.start()

    def note_resize(self) -> None:
        self._scaled = QPixmap()
        self._old_scaled = QPixmap()
        self._scaled_size = QSize()

    def _cover(self, source: QPixmap, target_attr: str, size: QSize) -> QPixmap:
        cached = getattr(self, target_attr)
        if source.isNull() or size.width() < 2 or size.height() < 2:
            return QPixmap()
        if not cached.isNull() and cached.size() == size:
            return cached
        scaled = source.scaled(size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
        x = max(0, (scaled.width() - size.width()) // 2)
        y = max(0, (scaled.height() - size.height()) // 2)
        cropped = scaled.copy(x, y, size.width(), size.height())
        setattr(self, target_attr, cropped)
        return cropped

    def paint_on(self, widget: QWidget) -> None:
        painter = QPainter(widget)
        page = QColor(self.theme.palette.bg)
        painter.fillRect(widget.rect(), page)
        size = widget.size()
        if self._opacity <= 0.01 or self._base.isNull():
            painter.end()
            return
        current = self._cover(self._base, "_scaled", size)
        if self._mix < 0.999 and not self._old.isNull():
            previous = self._cover(self._old, "_old_scaled", size)
            if not previous.isNull():
                painter.setOpacity(self._opacity * (1.0 - self._mix))
                painter.drawPixmap(0, 0, previous)
        if not current.isNull():
            painter.setOpacity(self._opacity * self._mix)
            painter.drawPixmap(0, 0, current)
        painter.setOpacity(1.0)
        if self.theme.mode == "dark":
            veil = QColor(0, 0, 0, int(168 * self._opacity))
        else:
            veil = QColor(page)
            veil.setAlpha(int(214 * self._opacity))
        painter.fillRect(widget.rect(), veil)
        painter.end()


class AmbientStage(QWidget):
    """Page stack floating on top of the hover backdrop."""

    def __init__(self, ambient: AmbientBackdrop, stack: QWidget, parent=None):
        super().__init__(parent)
        self.ambient = ambient
        self.stack = stack
        ambient.setParent(self)
        ambient.hide()
        stack.setParent(self)
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

    def resizeEvent(self, event) -> None:
        self.ambient.note_resize()
        super().resizeEvent(event)
        self._fit()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._fit()

    def paintEvent(self, _event) -> None:
        self.ambient.paint_on(self)

    def _fit(self) -> None:
        self.stack.setGeometry(self.rect())
        self.stack.raise_()


class TitleHero(QWidget):
    """Title page banner: blurred backdrop, poster on the left, title on the right."""

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.setFixedHeight(460)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._image = None
        self._backdrop = QPixmap()
        self._backdrop_key = (0, 0, 0)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._render_backdrop)
        self.poster = QLabel()
        self.poster.setFixedSize(214, 320)
        self.poster.setAlignment(Qt.AlignmentFlag.AlignCenter)
        shadow = QGraphicsDropShadowEffect(self.poster)
        shadow.setBlurRadius(36)
        shadow.setOffset(0, 12)
        shadow.setColor(QColor(0, 0, 0, 170))
        self.poster.setGraphicsEffect(shadow)
        self.column = QVBoxLayout()
        self.column.setSpacing(10)
        self.column.setContentsMargins(0, 0, 0, 8)
        self.column.addStretch(1)
        row = QHBoxLayout()
        row.setSpacing(28)
        row.setAlignment(Qt.AlignmentFlag.AlignBottom)
        row.addLayout(self.column, 1)
        row.addWidget(self.poster, 0, Qt.AlignmentFlag.AlignBottom)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(36, 24, 36, 28)
        outer.addStretch(1)
        outer.addLayout(row)
        self._paint_poster(None)
        self.theme.changed.connect(self.update)

    def clear(self) -> None:
        self._image = None
        self._backdrop = QPixmap()
        self._backdrop_key = (0, 0, 0)
        self._paint_poster(None)
        self.update()

    def set_backdrop(self, image) -> None:
        self._image = image
        self._backdrop_key = (0, 0, 0)
        self._render_backdrop()

    def set_poster(self, image) -> None:
        self._paint_poster(image)

    def _paint_poster(self, image) -> None:
        width, height, radius = 214, 320, 20
        pixmap = cover_pixmap(image, width, height, radius)
        if image is None or image.isNull():
            pixmap = QPixmap(width, height)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#181818"))
            painter.drawRoundedRect(QRectF(0, 0, width, height), radius, radius)
            painter.end()
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(255, 255, 255, 56))
        pen.setWidthF(1.5)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(1, 1, width - 2, height - 2), radius, radius)
        painter.end()
        self.poster.setPixmap(pixmap)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._timer.start(40)

    def _render_backdrop(self) -> None:
        key = (self.width(), self.height(), id(self._image) if self._image is not None else 0)
        if key[0] < 20 or key == self._backdrop_key:
            return
        self._backdrop = blurred_cover(self._image, key[0], key[1], 18)
        self._backdrop_key = key
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._backdrop.isNull():
            painter.fillRect(self.rect(), QColor("#050505"))
        else:
            painter.drawPixmap(0, 0, self._backdrop)
        fade = QColor("#050505")
        vertical = QLinearGradient(0, self.height() * 0.08, 0, self.height())
        top = QColor(fade)
        top.setAlpha(30)
        mid = QColor(fade)
        mid.setAlpha(120)
        bottom = QColor(fade)
        bottom.setAlpha(250)
        vertical.setColorAt(0, top)
        vertical.setColorAt(0.42, mid)
        vertical.setColorAt(1, bottom)
        painter.fillRect(self.rect(), vertical)
        side = QLinearGradient(0, 0, self.width(), 0)
        clear = QColor(fade)
        clear.setAlpha(0)
        soft = QColor(fade)
        soft.setAlpha(70)
        strong = QColor(fade)
        strong.setAlpha(210)
        side.setColorAt(0, clear)
        side.setColorAt(0.42, soft)
        side.setColorAt(1, strong)
        painter.fillRect(self.rect(), side)
        ember = QLinearGradient(0, self.height() * 0.55, 0, self.height())
        ember.setColorAt(0, QColor(229, 9, 20, 0))
        ember.setColorAt(1, QColor(229, 9, 20, 36))
        painter.fillRect(self.rect(), ember)
        page = QColor(self.theme.palette.bg)
        lip = QLinearGradient(0, self.height() - 28, 0, self.height())
        lip.setColorAt(0, QColor(page.red(), page.green(), page.blue(), 0))
        lip.setColorAt(1, page)
        painter.fillRect(self.rect(), lip)
        painter.end()


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
            "border-radius: 22px; padding: 10px 16px; font-weight: 600;"
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
