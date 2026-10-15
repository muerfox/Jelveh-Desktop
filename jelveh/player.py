"""Full-window player. Files are streamed through the jelveh.top media proxy."""

from __future__ import annotations

from PySide6.QtCore import QSizeF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .api import link_label, normalize_links, preferred_link_index


def _clock(ms: int) -> str:
    seconds = max(0, int(ms / 1000))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


class PlayerPage(QWidget):
    closed = Signal()
    progress = Signal(dict)

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.setObjectName("page")
        self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.detail: dict | None = None
        self.episode: dict | None = None
        self.links: list[dict] = []
        self.index = 0
        self._resume = 0
        self._seeking = False
        self._ready = False
        self.player: QMediaPlayer | None = None
        self.audio: QAudioOutput | None = None
        self.video_item: QGraphicsVideoItem | None = None

        self.scene = QGraphicsScene(self)
        self.scene.setBackgroundBrush(QColor("#000000"))
        self.view = QGraphicsView(self.scene, self)
        self.view.setFrameShape(QFrame.Shape.NoFrame)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setStyleSheet("background: #000; border: none;")
        self.view.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.chrome = QWidget(self)
        self.chrome.setStyleSheet("background: transparent;")
        column = QVBoxLayout(self.chrome)
        column.setContentsMargins(20, 16, 20, 18)
        top = QHBoxLayout()
        self.back = QPushButton("بستن")
        self.back.setObjectName("ghost")
        self.back.clicked.connect(self.close_player)
        self.heading = QLabel("پخش")
        self.heading.setStyleSheet("color: white; font-weight: 700; font-size: 16px; background: transparent;")
        self.subheading = QLabel("")
        self.subheading.setStyleSheet("color: #d0d0d0; background: transparent;")
        titles = QVBoxLayout()
        titles.addWidget(self.heading)
        titles.addWidget(self.subheading)
        top.addWidget(self.back)
        top.addSpacing(12)
        top.addLayout(titles, 1)
        self.quality = QComboBox()
        self.quality.setMinimumWidth(220)
        self.quality.currentIndexChanged.connect(self._quality_changed)
        top.addWidget(self.quality)
        column.addLayout(top)
        column.addStretch(1)
        self.message = QLabel("")
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message.setStyleSheet("color: white; background: rgba(0,0,0,0.55); border-radius: 12px; padding: 12px;")
        self.message.hide()
        column.addWidget(self.message, alignment=Qt.AlignmentFlag.AlignCenter)
        column.addStretch(1)

        bottom = QVBoxLayout()
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.sliderPressed.connect(self._begin_seek)
        self.slider.sliderReleased.connect(self._end_seek)
        time_row = QHBoxLayout()
        self.elapsed = QLabel("0:00")
        self.duration = QLabel("0:00")
        for label in (self.elapsed, self.duration):
            label.setStyleSheet("color: white; background: transparent;")
        time_row.addWidget(self.elapsed)
        time_row.addStretch(1)
        time_row.addWidget(self.duration)
        controls = QHBoxLayout()
        self.play_button = QPushButton("توقف")
        self.play_button.setObjectName("primary")
        self.play_button.clicked.connect(self.toggle)
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(80)
        self.volume.setFixedWidth(110)
        self.volume.valueChanged.connect(self._set_volume)
        self.full = QPushButton("تمام‌صفحه")
        self.full.setObjectName("ghost")
        self.full.clicked.connect(self.toggle_fullscreen)
        controls.addWidget(self.play_button)
        controls.addStretch(1)
        volume_label = QLabel("صدا")
        volume_label.setStyleSheet("color: white; background: transparent;")
        controls.addWidget(volume_label)
        controls.addWidget(self.volume)
        controls.addWidget(self.full)
        bottom.addWidget(self.slider)
        bottom.addLayout(time_row)
        bottom.addLayout(controls)
        column.addLayout(bottom)

        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self._autohide)
        self.save_timer = QTimer(self)
        self.save_timer.setInterval(5000)
        self.save_timer.timeout.connect(self._emit_progress)
        self.setMouseTracking(True)
        self.view.setMouseTracking(True)
        self.view.viewport().installEventFilter(self)

    def play(self, detail: dict, episode: dict | None = None, index: int | None = None, resume_ms: int = 0) -> None:
        self.detail = detail
        self.episode = episode
        raw = (episode or detail).get("download_links") or []
        self.links = normalize_links(raw)
        self._resume = max(0, int(resume_ms or 0))
        self.heading.setText(detail.get("title") or "")
        if episode:
            number = episode.get("episode_number") or ""
            name = episode.get("name") or ""
            self.subheading.setText(f"قسمت {number}" + (f" — {name}" if name else ""))
        else:
            self.subheading.setText(detail.get("original_title") or "")
        self.quality.blockSignals(True)
        self.quality.clear()
        for link in self.links:
            self.quality.addItem(link_label(link))
        chosen = preferred_link_index(self.links) if index is None else index
        if self.links:
            self.quality.setCurrentIndex(max(0, min(chosen, len(self.links) - 1)))
        self.quality.blockSignals(False)
        self.message.hide()
        self._ensure_player()
        if not self.links:
            self.message.setText("لینک پخشی برای این عنوان ثبت نشده است.")
            self.message.show()
            self.player.stop()
            return
        self._start(self.quality.currentIndex(), keep_position=False)
        self.setFocus()
        self._show_chrome()

    def _ensure_player(self) -> None:
        if self.player is not None:
            return
        self.video_item = QGraphicsVideoItem()
        self.video_item.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self.scene.addItem(self.video_item)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(self.volume.value() / 100)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video_item)
        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(self._on_duration)
        self.player.playbackStateChanged.connect(self._on_state)
        self.player.errorOccurred.connect(self._on_error)
        self.player.mediaStatusChanged.connect(self._on_status)
        self._fit_video()

    def _start(self, index: int, keep_position: bool) -> None:
        if not self.links or self.player is None:
            return
        self.index = max(0, min(index, len(self.links) - 1))
        if keep_position and self.player.position() > 0:
            self._resume = self.player.position()
        link = self.links[self.index]
        self.message.setText("در حال آماده‌سازی پخش…")
        self.message.show()
        self.player.setSource(QUrl(link["play_url"]))
        self.player.play()
        self.save_timer.start()

    def _quality_changed(self, index: int) -> None:
        if self.player and self.links and index >= 0 and index != self.index:
            self._start(index, keep_position=True)

    def toggle(self) -> None:
        if not self.player:
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def toggle_fullscreen(self) -> None:
        window = self.window()
        if window.isFullScreen():
            window.showNormal()
        else:
            window.showFullScreen()

    def close_player(self) -> None:
        self._emit_progress()
        self.save_timer.stop()
        if self.player:
            self.player.stop()
        if self.window().isFullScreen():
            self.window().showNormal()
        self.closed.emit()

    def _begin_seek(self) -> None:
        self._seeking = True

    def _end_seek(self) -> None:
        self._seeking = False
        if self.player:
            self.player.setPosition(self.slider.value())

    def _on_position(self, position: int) -> None:
        if not self._seeking:
            self.slider.setValue(position)
        self.elapsed.setText(_clock(position))

    def _on_duration(self, duration: int) -> None:
        self.slider.setRange(0, max(0, duration))
        self.duration.setText(_clock(duration))
        if self._resume and duration > 0:
            self.player.setPosition(min(self._resume, max(0, duration - 2000)))
            self._resume = 0

    def _on_state(self, state) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.play_button.setText("توقف" if playing else "پخش")
        if playing:
            self.message.hide()

    def _on_status(self, status) -> None:
        if status == QMediaPlayer.MediaStatus.BufferedMedia:
            self.message.hide()
        elif status == QMediaPlayer.MediaStatus.InvalidMedia:
            self._fail_over("این فایل پخش نشد.")

    def _on_error(self, _error, message: str) -> None:
        self._fail_over(message or "پخش این کیفیت ممکن نشد.")

    def _fail_over(self, message: str) -> None:
        if self.index + 1 < len(self.links):
            self.quality.setCurrentIndex(self.index + 1)
            return
        self.message.setText(message or "پخش این فایل ممکن نشد. کیفیت دیگری را امتحان کنید.")
        self.message.show()

    def _set_volume(self, value: int) -> None:
        if self.audio:
            self.audio.setVolume(value / 100)

    def _emit_progress(self) -> None:
        if not self.player or not self.detail:
            return
        duration = self.player.duration()
        position = self.player.position()
        if duration <= 0 or position <= 0:
            return
        episode = self.episode or {}
        self.progress.emit(
            {
                "type": "series" if self.episode else (self.detail.get("type") or "movie"),
                "id": self.detail.get("id"),
                "title": self.detail.get("title") or "",
                "poster": self.detail.get("poster"),
                "episode_id": episode.get("id"),
                "episode_label": self.subheading.text(),
                "position": position,
                "duration": duration,
            }
        )

    def _show_chrome(self) -> None:
        self.chrome.show()
        self.hide_timer.start(2800)

    def _autohide(self) -> None:
        if self.player and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.chrome.hide()

    def mouseMoveEvent(self, event) -> None:
        self._show_chrome()
        super().mouseMoveEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        self.toggle_fullscreen()
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Space, Qt.Key.Key_K):
            self.toggle()
        elif key == Qt.Key.Key_Escape:
            if self.window().isFullScreen():
                self.window().showNormal()
            else:
                self.close_player()
        elif key == Qt.Key.Key_F:
            self.toggle_fullscreen()
        elif key == Qt.Key.Key_Left and self.player:
            self.player.setPosition(max(0, self.player.position() - 10000))
        elif key == Qt.Key.Key_Right and self.player:
            self.player.setPosition(self.player.position() + 10000)
        elif key == Qt.Key.Key_Up:
            self.volume.setValue(min(100, self.volume.value() + 5))
        elif key == Qt.Key.Key_Down:
            self.volume.setValue(max(0, self.volume.value() - 5))
        elif key == Qt.Key.Key_M and self.audio:
            self.audio.setMuted(not self.audio.isMuted())
        else:
            super().keyPressEvent(event)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.view.viewport() and event.type() == event.Type.MouseMove:
            self._show_chrome()
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.view.setGeometry(self.rect())
        self.chrome.setGeometry(self.rect())
        self.chrome.raise_()
        self._fit_video()

    def _fit_video(self) -> None:
        size = self.view.viewport().size()
        self.scene.setSceneRect(0, 0, size.width(), size.height())
        if self.video_item is not None:
            self.video_item.setSize(QSizeF(size.width(), size.height()))
            self.video_item.setPos(0, 0)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.setFocus()
        QTimer.singleShot(0, self._fit_video)
