"""Full-window player. Files are streamed through the jelveh.top media proxy."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor
from PySide6.QtMultimedia import QAudioOutput, QMediaMetaData, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .api import link_label, normalize_links, preferred_link_index
from .widgets import CompactCombo

SKIP_MS = 10_000
UI_TICK_MS = 250
CHROME_HIDE_MS = 3000


def _clock(ms: int) -> str:
    seconds = max(0, int(ms / 1000))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _subtitle_label(meta: QMediaMetaData, index: int) -> str:
    language = meta.stringValue(QMediaMetaData.Key.Language) or ""
    title = meta.stringValue(QMediaMetaData.Key.Title) or ""
    return title or language or f"زیرنویس {index + 1}"


def _prefers_persian(meta: QMediaMetaData) -> bool:
    blob = f"{meta.stringValue(QMediaMetaData.Key.Language)} {meta.stringValue(QMediaMetaData.Key.Title)}".lower()
    return any(token in blob for token in ("fa", "per", "fas", "farsi", "persian", "فارسی"))


class _VideoSurface(QVideoWidget):
    """Emits when the picture area actually changes size, as fullscreen does."""

    resized = Signal()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        old = event.oldSize()
        if not old.isValid():
            return
        if abs(event.size().width() - old.width()) > 64 or abs(event.size().height() - old.height()) > 64:
            self.resized.emit()


class _LoadingPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(self.backgroundRole(), QColor("#050505"))
        self.setPalette(palette)
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.addStretch(1)
        self.caption = QLabel("در حال بارگذاری")
        self.caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.caption.setStyleSheet("color: white; font-size: 20px; font-weight: 700; background: transparent;")
        self.detail = QLabel("اتصال به پخش…")
        self.detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail.setWordWrap(True)
        self.detail.setStyleSheet("color: #d0d0d0; font-size: 13px; background: transparent;")
        self.bar = QProgressBar()
        self.bar.setObjectName("playerLoad")
        self.bar.setRange(0, 0)
        self.bar.setTextVisible(False)
        self.bar.setFixedSize(360, 18)
        layout.addWidget(self.caption, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.detail, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.bar, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addStretch(1)
        self.setStyleSheet(
            """
            QProgressBar#playerLoad {
                background: #242424;
                border: none;
                border-radius: 9px;
                min-height: 18px;
                max-height: 18px;
            }
            QProgressBar#playerLoad::chunk {
                background: #e50914;
                border-radius: 9px;
            }
            """
        )

    def busy(self, text: str) -> None:
        self.caption.setText("در حال بارگذاری")
        self.detail.setText(text)
        self.bar.show()
        self.bar.setRange(0, 0)

    def percent(self, value: int) -> None:
        self.caption.setText("در حال بارگذاری")
        self.detail.setText(f"{value}٪ از شروع پخش")
        self.bar.show()
        self.bar.setRange(0, 100)
        self.bar.setValue(value)

    def error(self, text: str) -> None:
        self.caption.setText("پخش ممکن نشد")
        self.detail.setText(text)
        self.bar.hide()


class PlayerPage(QWidget):
    closed = Signal()
    progress = Signal(dict)

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.session = session
        self.theme = session.theme
        self.setObjectName("player")
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(self.backgroundRole(), QColor("#000000"))
        self.setPalette(palette)
        self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.detail: dict | None = None
        self.episode: dict | None = None
        self.links: list[dict] = []
        self.index = 0
        self._resume = 0
        self._seeking = False
        self._muted = False
        self._volume_before_mute = 80
        self._click_armed = False
        self._revealed = False
        self._attaching = False
        self._window_filtered = False
        self._hovering = False
        self._hiding = False
        self._chrome_visible = True
        self.player: QMediaPlayer | None = None
        self.audio: QAudioOutput | None = None
        self._subs_ready = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.loading = _LoadingPanel()
        self.video = _VideoSurface()
        self.video.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.video.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self.video.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.video.setMinimumSize(QSize(320, 180))
        self.video.setMouseTracking(True)
        self.video.resized.connect(self._schedule_rebind)
        self.stage = QStackedWidget()
        self.stage.setAutoFillBackground(True)
        stage_palette = self.stage.palette()
        stage_palette.setColor(self.stage.backgroundRole(), QColor("#000000"))
        self.stage.setPalette(stage_palette)
        self.stage.setMouseTracking(True)
        self.stage.addWidget(self.loading)
        self.stage.addWidget(self.video)
        self.stage.setCurrentWidget(self.loading)
        root.addWidget(self.stage, 1)

        self.top = QWidget(self)
        self.top.setObjectName("playerTop")
        self.top.setFixedHeight(68)
        top_row = QHBoxLayout(self.top)
        top_row.setContentsMargins(16, 10, 16, 10)
        top_row.setSpacing(10)
        self.back = QPushButton("بستن")
        self.back.setObjectName("ghost")
        self.back.clicked.connect(self.close_player)
        self.heading = QLabel("پخش")
        self.heading.setStyleSheet("color: white; font-weight: 700; font-size: 16px; background: transparent;")
        self.subheading = QLabel("")
        self.subheading.setStyleSheet("color: #bdbdbd; background: transparent;")
        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addWidget(self.heading)
        titles.addWidget(self.subheading)
        self.quality = CompactCombo()
        self.quality.setMinimumWidth(180)
        self.quality.currentIndexChanged.connect(self._quality_changed)
        self.subs = CompactCombo()
        self.subs.setMinimumWidth(140)
        self.subs.addItem("زیرنویس", -1)
        self.subs.currentIndexChanged.connect(self._subtitle_changed)
        self.download_button = QPushButton("دانلود")
        self.download_button.setObjectName("ghost")
        self.download_button.clicked.connect(self._download_current)
        top_row.addLayout(titles, 1)
        top_row.addWidget(self.quality)
        top_row.addWidget(self.subs)
        top_row.addWidget(self.download_button)
        top_row.addWidget(self.back)

        self.bottom = QWidget(self)
        self.bottom.setObjectName("playerBottom")
        self.bottom.setFixedHeight(96)
        bottom_col = QVBoxLayout(self.bottom)
        bottom_col.setContentsMargins(16, 10, 16, 12)
        bottom_col.setSpacing(8)

        progress = QHBoxLayout()
        progress.setSpacing(12)
        self.elapsed = QLabel("0:00")
        self.duration = QLabel("0:00")
        for label in (self.elapsed, self.duration):
            label.setStyleSheet("color: white; background: transparent; font-size: 12px; min-width: 52px;")
        self.elapsed.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.duration.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setObjectName("playerSeek")
        self.slider.setRange(0, 0)
        self.slider.setPageStep(SKIP_MS)
        self.slider.setSingleStep(1000)
        self.slider.setMinimumHeight(22)
        self.slider.sliderPressed.connect(self._begin_seek)
        self.slider.sliderMoved.connect(self._scrub)
        self.slider.sliderReleased.connect(self._end_seek)
        progress.addWidget(self.elapsed)
        progress.addWidget(self.slider, 1)
        progress.addWidget(self.duration)
        bottom_col.addLayout(progress)

        controls = QHBoxLayout()
        controls.setSpacing(10)
        self.back_skip = QPushButton("۱۰−")
        self.back_skip.setObjectName("ghost")
        self.back_skip.setToolTip("۱۰ ثانیه عقب")
        self.back_skip.clicked.connect(lambda: self.skip(-SKIP_MS))
        self.play_button = QPushButton("پخش")
        self.play_button.setObjectName("primary")
        self.play_button.setFixedWidth(96)
        self.play_button.clicked.connect(self.toggle)
        self.forward_skip = QPushButton("۱۰+")
        self.forward_skip.setObjectName("ghost")
        self.forward_skip.setToolTip("۱۰ ثانیه جلو")
        self.forward_skip.clicked.connect(lambda: self.skip(SKIP_MS))
        self.buffer_label = QLabel("")
        self.buffer_label.setStyleSheet("color: #ffc857; background: transparent; font-size: 12px;")
        self.buffer_label.hide()
        self.mute = QPushButton("صدا")
        self.mute.setObjectName("ghost")
        self.mute.clicked.connect(self.toggle_mute)
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setObjectName("playerVolume")
        self.volume.setRange(0, 100)
        self.volume.setValue(80)
        self.volume.setFixedWidth(120)
        self.volume.valueChanged.connect(self._set_volume)
        self.full = QPushButton("تمام‌صفحه")
        self.full.setObjectName("ghost")
        self.full.clicked.connect(self.toggle_fullscreen)
        controls.addWidget(self.back_skip)
        controls.addWidget(self.play_button)
        controls.addWidget(self.forward_skip)
        controls.addWidget(self.buffer_label)
        controls.addStretch(1)
        controls.addWidget(self.mute)
        controls.addWidget(self.volume)
        controls.addWidget(self.full)
        bottom_col.addLayout(controls)

        for button in (
            self.back,
            self.download_button,
            self.back_skip,
            self.play_button,
            self.forward_skip,
            self.mute,
            self.full,
        ):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setAutoDefault(False)
            button.setDefault(False)
        self._apply_player_chrome_style()

        self.save_timer = QTimer(self)
        self.save_timer.setInterval(5000)
        self.save_timer.timeout.connect(self._emit_progress)
        self.ui_timer = QTimer(self)
        self.ui_timer.setInterval(UI_TICK_MS)
        self.ui_timer.timeout.connect(self._tick_ui)
        self.click_timer = QTimer(self)
        self.click_timer.setSingleShot(True)
        self.click_timer.setInterval(220)
        self.click_timer.timeout.connect(self._single_click)
        self.load_timer = QTimer(self)
        self.load_timer.setSingleShot(True)
        self.load_timer.timeout.connect(self._reveal_video)
        self._surface_timer = QTimer(self)
        self._surface_timer.setSingleShot(True)
        self._surface_timer.timeout.connect(self._rebind_video)
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self._autohide)
        self.setMouseTracking(True)
        self.video.installEventFilter(self)
        self.stage.installEventFilter(self)
        self.top.installEventFilter(self)
        self.bottom.installEventFilter(self)
        self.session.downloads.updated.connect(self._refresh_download_button)
        self._show_chrome()

    def _apply_player_chrome_style(self) -> None:
        style = """
            QWidget#playerTop, QWidget#playerBottom {
                background: rgba(8, 8, 8, 230);
            }
            QWidget#playerTop QPushButton#ghost,
            QWidget#playerBottom QPushButton#ghost {
                background: rgba(255, 255, 255, 0.10);
                color: #ffffff;
                border: 1px solid rgba(255, 255, 255, 0.38);
                border-radius: 18px;
                min-height: 36px;
                max-height: 36px;
                padding: 0px 16px;
                font-weight: 700;
            }
            QWidget#playerTop QPushButton#ghost:hover,
            QWidget#playerBottom QPushButton#ghost:hover {
                background: rgba(255, 255, 255, 0.20);
                border-color: rgba(255, 255, 255, 0.65);
            }
            QWidget#playerTop QPushButton#ghost:pressed,
            QWidget#playerBottom QPushButton#ghost:pressed {
                background: rgba(255, 255, 255, 0.34);
                border-color: #ffffff;
                padding-top: 2px;
            }
            QWidget#playerBottom QPushButton#primary {
                background: #e50914;
                color: #ffffff;
                border: 1px solid #e50914;
                border-radius: 18px;
                min-height: 36px;
                max-height: 36px;
                font-weight: 800;
            }
            QWidget#playerBottom QPushButton#primary:hover {
                background: #ff1a1a;
                border-color: #ff1a1a;
            }
            QWidget#playerBottom QPushButton#primary:pressed {
                background: #b00710;
                border-color: #b00710;
                padding-top: 2px;
            }
            QSlider#playerSeek::groove:horizontal {
                height: 14px;
                background: rgba(255, 255, 255, 0.22);
                border-radius: 7px;
            }
            QSlider#playerSeek::sub-page:horizontal {
                background: #e50914;
                border-radius: 7px;
            }
            QSlider#playerSeek::handle:horizontal {
                width: 20px;
                height: 20px;
                margin: -3px 0;
                border-radius: 10px;
                background: #ffffff;
                border: 1px solid rgba(0, 0, 0, 0.35);
            }
            QSlider#playerVolume::groove:horizontal {
                height: 4px;
                background: rgba(255, 255, 255, 0.28);
                border-radius: 2px;
            }
            QSlider#playerVolume::sub-page:horizontal {
                background: rgba(255, 255, 255, 0.85);
                border-radius: 2px;
            }
            QSlider#playerVolume::handle:horizontal {
                width: 12px;
                height: 12px;
                margin: -4px 0;
                border-radius: 6px;
                background: #ffffff;
            }
            """
        self.top.setStyleSheet(style)
        self.bottom.setStyleSheet(style)

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
        self._ensure_player()
        if not self.links:
            self._show_error("لینک پخشی برای این عنوان ثبت نشده است.")
            self.player.stop()
            self.ui_timer.stop()
            return
        self._start(self.quality.currentIndex(), keep_position=False)
        self.setFocus()
        self._show_chrome()

    def _ensure_player(self) -> None:
        if self.player is not None:
            return
        self.audio = QAudioOutput(self)
        self.audio.setVolume(self.volume.value() / 100)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)
        self.player.durationChanged.connect(self._on_duration)
        self.player.playbackStateChanged.connect(self._on_state)
        self.player.errorOccurred.connect(self._on_error)
        self.player.mediaStatusChanged.connect(self._on_status)
        self.player.bufferProgressChanged.connect(self._on_buffer)
        self.player.tracksChanged.connect(self._load_subtitles)
        sink = self.video.videoSink()
        if sink is not None:
            sink.videoFrameChanged.connect(self._on_video_frame)

    def _start(self, index: int, keep_position: bool) -> None:
        if not self.links or self.player is None:
            return
        self.index = max(0, min(index, len(self.links) - 1))
        if keep_position and self.player.position() > 0:
            self._resume = self.player.position()
        link = self.links[self.index]
        self._subs_ready = False
        self.slider.setRange(0, 0)
        self.elapsed.setText("0:00")
        self.duration.setText("0:00")
        self._begin_loading("اتصال به پخش…")
        local = self.session.downloads.ready_path(link["play_url"])
        source = QUrl.fromLocalFile(local) if local else QUrl(link["play_url"])
        self._refresh_download_button()
        self.player.setSource(source)
        self.player.play()
        self.save_timer.start()
        self.ui_timer.start()

    def play_local(self, path: str, title: str) -> None:
        self.detail = {"title": title, "type": "movie", "id": None, "poster": None}
        self.episode = None
        self.links = []
        self.heading.setText(title)
        self.subheading.setText("فایل ذخیره‌شده")
        self.quality.blockSignals(True)
        self.quality.clear()
        self.quality.blockSignals(False)
        self.download_button.setText("دانلود شده")
        self._ensure_player()
        self._subs_ready = False
        self._begin_loading("باز کردن فایل…")
        self.player.setSource(QUrl.fromLocalFile(path))
        self.player.play()
        self.save_timer.start()
        self.ui_timer.start()
        self.setFocus()
        self._show_chrome()

    def _begin_loading(self, text: str) -> None:
        self._revealed = False
        self.buffer_label.hide()
        self.loading.busy(text)
        self.stage.setCurrentWidget(self.loading)
        self.load_timer.start(12000)
        self._show_chrome()

    def _reveal_video(self) -> None:
        if self._revealed:
            return
        self._revealed = True
        self.load_timer.stop()
        self.buffer_label.hide()
        self.stage.setCurrentWidget(self.video)
        self._show_chrome()

    def _show_error(self, text: str) -> None:
        self._revealed = False
        self.load_timer.stop()
        self.loading.error(text)
        self.stage.setCurrentWidget(self.loading)
        self._show_chrome()

    def _on_buffer(self, progress: float) -> None:
        if self._revealed:
            return
        percent = int(max(0.0, min(1.0, float(progress))) * 100)
        if percent <= 0:
            self.loading.busy("در حال بافر…")
            return
        self.loading.percent(percent)
        if percent >= 12:
            self._reveal_video()

    def _on_video_frame(self, frame) -> None:
        if self._revealed or frame is None or not frame.isValid():
            return
        self._reveal_video()

    def _download_current(self) -> None:
        if not self.links:
            return
        link = self.links[self.index]
        title = self.heading.text()
        if self.subheading.text():
            title = f"{title} {self.subheading.text()}"
        self.session.downloads.start(url=link["play_url"], title=title, detail=link_label(link))
        self._refresh_download_button()

    def _refresh_download_button(self) -> None:
        if not self.isVisible() or not self.links:
            return
        link = self.links[self.index]
        item = self.session.downloads.find_url(link["play_url"])
        if not item:
            local = self.session.downloads.ready_path(link["play_url"])
            self.download_button.setText("دانلود شده" if local else "دانلود")
            return
        status = item.get("status")
        if status == "done":
            self.download_button.setText("دانلود شده")
        elif status == "paused":
            received = int(item.get("received") or 0)
            total = int(item.get("total") or 0)
            if total:
                self.download_button.setText(f"متوقف {int(received * 100 / total)}٪")
            else:
                self.download_button.setText("متوقف")
        elif status == "downloading":
            received = int(item.get("received") or 0)
            total = int(item.get("total") or 0)
            if total:
                self.download_button.setText(f"دانلود {int(received * 100 / total)}٪")
            else:
                self.download_button.setText("در حال دانلود")
        else:
            self.download_button.setText("دانلود")

    def _load_subtitles(self) -> None:
        if not self.player:
            return
        tracks = list(self.player.subtitleTracks())
        self.subs.blockSignals(True)
        self.subs.clear()
        self.subs.addItem("بدون زیرنویس", -1)
        chosen = 0
        for index, meta in enumerate(tracks):
            self.subs.addItem(_subtitle_label(meta, index), index)
            if _prefers_persian(meta):
                chosen = index
        if tracks:
            self.subs.setCurrentIndex(chosen + 1)
            self.player.setActiveSubtitleTrack(chosen)
        else:
            self.subs.setCurrentIndex(0)
            self.player.setActiveSubtitleTrack(-1)
        self.subs.blockSignals(False)
        self._subs_ready = True

    def _subtitle_changed(self, _index: int) -> None:
        if not self.player or not self._subs_ready:
            return
        track = self.subs.currentData()
        if track is None:
            return
        self.player.setActiveSubtitleTrack(int(track))

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
        self._show_chrome()

    def skip(self, delta_ms: int) -> None:
        if not self.player:
            return
        duration = self.player.duration()
        target = self.player.position() + delta_ms
        if duration > 0:
            target = max(0, min(target, duration))
        else:
            target = max(0, target)
        self.player.setPosition(target)
        self._refresh_progress(force=True)
        self._show_chrome()

    def toggle_mute(self) -> None:
        if not self.audio:
            return
        if self._muted or self.volume.value() == 0:
            self._muted = False
            restore = self._volume_before_mute or 80
            self.volume.setValue(restore)
        else:
            self._volume_before_mute = max(1, self.volume.value())
            self._muted = True
            self.volume.setValue(0)
        self._update_mute_label()
        self._show_chrome()

    def toggle_fullscreen(self) -> None:
        window = self.window()
        if window.isFullScreen():
            window.showNormal()
            self.full.setText("تمام‌صفحه")
        else:
            window.showFullScreen()
            self.full.setText("خروج")
        self._show_chrome()
        self._schedule_rebind()

    def _schedule_rebind(self) -> None:
        if self._attaching or not self._revealed:
            return
        self._surface_timer.start(200)

    def _rebind_video(self) -> None:
        if self._attaching or not self.player or not self.isVisible() or not self._revealed:
            return
        self._attaching = True
        was_playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        self.player.setVideoOutput(None)
        self.video.hide()
        self.video.show()
        self.player.setVideoOutput(self.video)
        if was_playing:
            self.player.play()
        self._attaching = False

    def close_player(self) -> None:
        self._emit_progress()
        self.save_timer.stop()
        self.ui_timer.stop()
        self.load_timer.stop()
        self._surface_timer.stop()
        self.hide_timer.stop()
        if self.player:
            self.player.stop()
        if self.window().isFullScreen():
            self.window().showNormal()
            self.full.setText("تمام‌صفحه")
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.closed.emit()

    def _begin_seek(self) -> None:
        self._seeking = True
        self.hide_timer.stop()
        self._show_chrome()

    def _scrub(self, position: int) -> None:
        self.elapsed.setText(_clock(position))

    def _end_seek(self) -> None:
        self._seeking = False
        if self.player:
            self.player.setPosition(self.slider.value())
        self._refresh_progress(force=True)
        self._show_chrome()

    def _tick_ui(self) -> None:
        self._refresh_progress()
        if not self._revealed and self.player and self.player.position() > 400:
            self._reveal_video()

    def _refresh_progress(self, force: bool = False) -> None:
        if not self.player or (self._seeking and not force):
            return
        position = self.player.position()
        duration = self.player.duration()
        if duration > 0 and self.slider.maximum() != duration:
            self.slider.setRange(0, duration)
            self.duration.setText(_clock(duration))
        if not self._seeking:
            self.slider.blockSignals(True)
            self.slider.setValue(position)
            self.slider.blockSignals(False)
        self.elapsed.setText(_clock(position))

    def _on_duration(self, duration: int) -> None:
        self.slider.setRange(0, max(0, duration))
        self.duration.setText(_clock(duration))
        if self._resume and duration > 0 and self.player:
            self.player.setPosition(min(self._resume, max(0, duration - 2000)))
            self._resume = 0
            self._refresh_progress(force=True)

    def _on_state(self, state) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.play_button.setText("مکث" if playing else "پخش")
        if not playing:
            self._refresh_progress(force=True)
            self._show_chrome()
        elif self._chrome_visible:
            self.hide_timer.start(CHROME_HIDE_MS)

    def _on_status(self, status) -> None:
        if status == QMediaPlayer.MediaStatus.BufferingMedia:
            if self._revealed:
                self.buffer_label.setText("در حال بافر…")
                self.buffer_label.show()
            else:
                self.loading.busy("در حال بافر…")
        elif status == QMediaPlayer.MediaStatus.BufferedMedia:
            self.buffer_label.hide()
            self._reveal_video()
            if self.player and self.player.subtitleTracks() and not self._subs_ready:
                self._load_subtitles()
        elif status == QMediaPlayer.MediaStatus.LoadedMedia:
            if self.player and self.player.subtitleTracks() and not self._subs_ready:
                self._load_subtitles()
        elif status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.buffer_label.hide()
            self.play_button.setText("پخش")
        elif status == QMediaPlayer.MediaStatus.LoadingMedia:
            if not self._revealed:
                self.loading.busy("اتصال به پخش…")
        elif status == QMediaPlayer.MediaStatus.InvalidMedia:
            self._fail_over("این فایل پخش نشد.")

    def _on_error(self, _error, message: str) -> None:
        self._fail_over(message or "پخش این کیفیت ممکن نشد.")

    def _fail_over(self, message: str) -> None:
        if self.index + 1 < len(self.links):
            self.quality.setCurrentIndex(self.index + 1)
            return
        self._show_error(message or "پخش این فایل ممکن نشد. کیفیت دیگری را امتحان کنید.")

    def _set_volume(self, value: int) -> None:
        if self.audio:
            self.audio.setVolume(value / 100)
        if value > 0:
            self._muted = False
            self._volume_before_mute = value
        else:
            self._muted = True
        self._update_mute_label()

    def _update_mute_label(self) -> None:
        self.mute.setText("بی‌صدا" if self._muted or self.volume.value() == 0 else "صدا")

    def _emit_progress(self) -> None:
        if not self.player or not self.detail or not self.detail.get("id"):
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
        if self._hiding:
            return
        self._chrome_visible = True
        self.top.show()
        self.bottom.show()
        self._place_chrome()
        self.setCursor(Qt.CursorShape.ArrowCursor)
        if self._should_keep_chrome():
            self.hide_timer.stop()
        else:
            self.hide_timer.start(CHROME_HIDE_MS)

    def _should_keep_chrome(self) -> bool:
        if self._seeking or not self._revealed:
            return True
        if not self.player:
            return True
        return self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState

    def _autohide(self) -> None:
        if self._should_keep_chrome():
            return
        self._hiding = True
        self._chrome_visible = False
        self._hovering = False
        self.top.hide()
        self.bottom.hide()
        self._hiding = False
        self.setCursor(Qt.CursorShape.BlankCursor)

    def _place_chrome(self) -> None:
        width = self.width()
        height = self.height()
        self.top.setGeometry(0, 0, width, self.top.height() or 68)
        self.bottom.setGeometry(0, max(0, height - (self.bottom.height() or 96)), width, self.bottom.height() or 96)
        self.top.raise_()
        self.bottom.raise_()

    def _single_click(self) -> None:
        if not self._click_armed:
            return
        self._click_armed = False
        if not self._chrome_visible:
            self._show_chrome()
            return
        self.toggle()

    def mouseMoveEvent(self, event) -> None:
        self._show_chrome()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:
        self._show_chrome()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        self._click_armed = False
        self.click_timer.stop()
        self.toggle_fullscreen()
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event) -> None:
        self._show_chrome()
        key = event.key()
        if key in (Qt.Key.Key_Space, Qt.Key.Key_K):
            self.toggle()
        elif key == Qt.Key.Key_Escape:
            if self.window().isFullScreen():
                self.toggle_fullscreen()
            else:
                self.close_player()
        elif key == Qt.Key.Key_F:
            self.toggle_fullscreen()
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_J):
            self.skip(-SKIP_MS)
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_L):
            self.skip(SKIP_MS)
        elif key == Qt.Key.Key_Up:
            self.volume.setValue(min(100, self.volume.value() + 5))
        elif key == Qt.Key.Key_Down:
            self.volume.setValue(max(0, self.volume.value() - 5))
        elif key == Qt.Key.Key_M:
            self.toggle_mute()
        else:
            super().keyPressEvent(event)

    def eventFilter(self, watched, event) -> bool:
        etype = event.type()
        if self._hiding:
            return super().eventFilter(watched, event)
        if watched is self.window() and etype == QEvent.Type.WindowStateChange:
            self._schedule_rebind()
        elif etype == QEvent.Type.MouseMove:
            if watched in (self.top, self.bottom):
                self._hovering = True
            self._show_chrome()
        elif etype == QEvent.Type.Enter and watched in (self.top, self.bottom):
            self._hovering = True
            self._show_chrome()
        elif etype == QEvent.Type.Leave and watched in (self.top, self.bottom):
            self._hovering = False
            self._show_chrome()
        elif etype == QEvent.Type.MouseButtonPress:
            self._show_chrome()
        elif etype == QEvent.Type.MouseButtonDblClick and watched is self.video:
            self._click_armed = False
            self.click_timer.stop()
            self.toggle_fullscreen()
            return True
        elif etype == QEvent.Type.MouseButtonRelease and watched is self.video:
            if event.button() == Qt.MouseButton.LeftButton:
                self._click_armed = True
                self.click_timer.start()
                return True
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_chrome()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        window = self.window()
        if window is not None and not self._window_filtered:
            window.installEventFilter(self)
            self._window_filtered = True
        self.setFocus()
        self._show_chrome()

    def hideEvent(self, event) -> None:
        self.ui_timer.stop()
        self.hide_timer.stop()
        self.setCursor(Qt.CursorShape.ArrowCursor)
        super().hideEvent(event)
