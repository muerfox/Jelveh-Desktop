"""Colors taken from jelveh.top (jet / ember / gold / mint) and Vazirmatn."""

from __future__ import annotations

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPainterPath, QPen, QPixmap

from .paths import asset


class Palette:
    def __init__(self, **colors: str):
        self.__dict__.update(colors)

    def qcolor(self, name: str, alpha: int = 255) -> QColor:
        color = QColor(getattr(self, name))
        color.setAlpha(alpha)
        return color


DARK = Palette(
    bg="#050505",
    bg_elev="#0a0a0a",
    surface="#111111",
    card="#181818",
    line="#242424",
    line_strong="#333333",
    muted="#8a8a8a",
    dim="#a8a8a8",
    text="#e8e8e8",
    ember="#e50914",
    ember_hot="#ff1a1a",
    gold="#ffc857",
    mint="#3ddc97",
    white="#ffffff",
    black="#000000",
    nav_active_bg="#ffffff",
    nav_active_fg="#0a0a0a",
    overlay="rgba(5, 5, 5, 0.72)",
    hero_fade="#050505",
)

LIGHT = Palette(
    bg="#f4f4f4",
    bg_elev="#ffffff",
    surface="#ffffff",
    card="#ececec",
    line="#e2e2e2",
    line_strong="#cfcfcf",
    muted="#6b6b6b",
    dim="#4a4a4a",
    text="#141414",
    ember="#e50914",
    ember_hot="#ff1a1a",
    gold="#b8860b",
    mint="#0f9d6a",
    white="#ffffff",
    black="#000000",
    nav_active_bg="#141414",
    nav_active_fg="#ffffff",
    overlay="rgba(255, 255, 255, 0.78)",
    hero_fade="#f4f4f4",
)


class Theme(QObject):
    changed = Signal()

    def __init__(self, mode: str = "dark"):
        super().__init__()
        self.mode = "light" if mode == "light" else "dark"
        self.family = "Vazirmatn"

    @property
    def palette(self) -> Palette:
        return LIGHT if self.mode == "light" else DARK

    def toggle(self) -> None:
        self.mode = "light" if self.mode == "dark" else "dark"
        self.changed.emit()

    def set_mode(self, mode: str) -> None:
        mode = "light" if mode == "light" else "dark"
        if mode != self.mode:
            self.mode = mode
            self.changed.emit()


def load_fonts() -> str:
    family = ""
    for filename in ("Vazirmatn-Regular.ttf", "Vazirmatn-Medium.ttf", "Vazirmatn-Bold.ttf"):
        font_id = QFontDatabase.addApplicationFont(str(asset("fonts", filename)))
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            family = families[0]
    return family or "Vazirmatn"


def app_font(family: str) -> QFont:
    font = QFont(family)
    font.setPixelSize(14)
    font.setWeight(QFont.Weight.Normal)
    return font


def _brand_image() -> QPixmap:
    path = asset("icon.png")
    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        fallback = QPixmap(256, 256)
        fallback.fill(QColor("#e50914"))
        return fallback
    return pixmap


def logo_pixmap(size: int = 36) -> QPixmap:
    source = _brand_image()
    return source.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def app_icon() -> QIcon:
    icon = QIcon()
    source = _brand_image()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(
            source.scaled(
                size,
                size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
    return icon


def search_icon(color: str = "#8a8a8a", size: int = 18) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(max(1.6, size * 0.12))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    lens = QRectF(size * 0.14, size * 0.14, size * 0.52, size * 0.52)
    painter.drawEllipse(lens)
    painter.drawLine(
        int(size * 0.62),
        int(size * 0.62),
        int(size * 0.86),
        int(size * 0.86),
    )
    painter.end()
    return QIcon(pixmap)


def _stroke_icon(size: int, color: str, draw) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(max(1.6, size * 0.11))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    draw(painter, size)
    painter.end()
    return QIcon(pixmap)


def sun_icon(color: str = "#ffc857", size: int = 18) -> QIcon:
    def draw(painter: QPainter, side: int) -> None:
        center = side / 2
        radius = side * 0.22
        painter.drawEllipse(QRectF(center - radius, center - radius, radius * 2, radius * 2))
        for index in range(8):
            angle = index * 45
            painter.save()
            painter.translate(center, center)
            painter.rotate(angle)
            painter.drawLine(int(side * 0.34), 0, int(side * 0.46), 0)
            painter.restore()

    return _stroke_icon(size, color, draw)


def moon_icon(color: str = "#e8e8e8", size: int = 18) -> QIcon:
    def draw(painter: QPainter, side: int) -> None:
        painter.setBrush(QColor(color))
        painter.setPen(Qt.PenStyle.NoPen)
        outer = QRectF(side * 0.16, side * 0.12, side * 0.7, side * 0.7)
        painter.drawEllipse(outer)
        painter.setBrush(QColor("#00000000"))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        cut = QRectF(side * 0.34, side * 0.08, side * 0.62, side * 0.62)
        painter.drawEllipse(cut)

    return _stroke_icon(size, color, draw)


def _thumb_icon(color: str, size: int, up: bool) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    if not up:
        painter.translate(0, size)
        painter.scale(1, -1)
    side = float(size)
    painter.drawRoundedRect(QRectF(side * 0.30, side * 0.46, side * 0.52, side * 0.40), side * 0.1, side * 0.1)
    painter.drawRoundedRect(QRectF(side * 0.16, side * 0.12, side * 0.24, side * 0.50), side * 0.12, side * 0.12)
    painter.end()
    return QIcon(pixmap)


def like_icon(color: str = "#3ddc97", size: int = 18) -> QIcon:
    return _thumb_icon(color, size, up=True)


def dislike_icon(color: str = "#e50914", size: int = 18) -> QIcon:
    return _thumb_icon(color, size, up=False)


def _baseline(metrics, top: float, height: float) -> float:
    return top + (height + metrics.ascent() - metrics.descent()) / 2


def imdb_logo(width: int = 34, height: int = 16) -> QPixmap:
    """Classic yellow IMDb mark. The word is centered in the yellow block."""
    width = max(int(width), 18)
    height = max(int(height), 10)
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#f5c518"))
    radius = height * 0.22
    painter.drawRoundedRect(QRectF(0, 0, width, height), radius, radius)
    font = QFont("Arial")
    font.setBold(True)
    font.setPixelSize(max(8, int(height * 0.62)))
    painter.setFont(font)
    painter.setPen(QColor("#0a0a0a"))
    metrics = painter.fontMetrics()
    text = "IMDb"
    advance = metrics.horizontalAdvance(text)
    painter.drawText(QPointF((width - advance) / 2, _baseline(metrics, 0, height)), text)
    painter.end()
    return pixmap


def imdb_icon(size: int = 18) -> QIcon:
    return QIcon(imdb_logo(max(size + 8, 28), max(size - 2, 14)))


def avatar_pixmap(name: str, size: int = 88, ember: str = "#e50914") -> QPixmap:
    """Circular initials avatar for the profile header."""
    size = max(int(size), 32)
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#181818"))
    painter.drawEllipse(0, 0, size, size)
    ring = QPen(QColor(ember))
    ring.setWidthF(max(2.0, size * 0.04))
    painter.setPen(ring)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    inset = ring.widthF()
    painter.drawEllipse(QRectF(inset / 2, inset / 2, size - inset, size - inset))
    initials = "".join(part[0] for part in (name or "ج").split() if part)[:2] or "ج"
    font = QFont("Vazirmatn")
    font.setBold(True)
    font.setPixelSize(int(size * 0.34))
    painter.setFont(font)
    painter.setPen(QColor("#ffffff"))
    painter.drawText(QRectF(0, 0, size, size), int(Qt.AlignmentFlag.AlignCenter), initials.upper())
    painter.end()
    return pixmap


def rating_chip_pixmap(score: str, dark: bool = True) -> QPixmap:
    """IMDb logo and score, both centered as a group inside the chip."""
    logo = imdb_logo(34, 16)
    font = QFont("Vazirmatn")
    font.setBold(True)
    font.setPixelSize(12)
    measure = QPixmap(1, 1)
    probe = QPainter(measure)
    probe.setFont(font)
    advance = probe.fontMetrics().horizontalAdvance(score)
    probe.end()
    pad_x, pad_y, gap = 6, 4, 5
    width = pad_x + logo.width() + gap + advance + pad_x
    height = max(logo.height() + pad_y * 2, 24)
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    bg = QColor(0, 0, 0, 185) if dark else QColor(255, 255, 255, 220)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(bg)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0.5, 0.5, width - 1, height - 1), height / 2, height / 2)
    painter.drawPath(path)
    content = logo.width() + gap + advance
    origin = (width - content) / 2
    painter.drawPixmap(int(origin), int((height - logo.height()) / 2), logo)
    painter.setFont(font)
    painter.setPen(QColor("#ffc857") if dark else QColor("#b8860b"))
    metrics = painter.fontMetrics()
    painter.drawText(QPointF(origin + logo.width() + gap, _baseline(metrics, 0, height)), score)
    painter.end()
    return pixmap


def stylesheet(theme: Theme) -> str:
    c = theme.palette
    family = theme.family
    return f"""
    * {{
        font-family: "{family}";
        outline: none;
    }}
    QMainWindow, QDialog, QWidget#page, QWidget#shell {{
        background: {c.bg};
        color: {c.text};
    }}
    QWidget#sidebar {{
        background: {c.bg_elev};
        border-left: 1px solid {c.line};
    }}
    QWidget#topbar {{
        background: {c.bg};
        border-bottom: 1px solid {c.line};
    }}
    QLabel {{
        background: transparent;
        color: {c.text};
    }}
    QLabel#muted {{ color: {c.muted}; }}
    QLabel#dim {{ color: {c.dim}; }}
    QLabel#gold {{ color: {c.gold}; font-weight: 700; }}
    QLabel#mint {{ color: {c.mint}; font-weight: 600; }}
    QLabel#section {{
        font-size: 20px;
        font-weight: 700;
        color: {c.text};
    }}
    QLabel#heroTitle {{
        font-size: 34px;
        font-weight: 700;
        color: #ffffff;
    }}
    QLabel#heroMeta, QLabel#heroOverview {{
        color: #f2f2f2;
    }}
    QLabel#logoWord {{
        font-size: 18px;
        font-weight: 700;
        letter-spacing: 1px;
    }}
    QPushButton {{
        background: transparent;
        color: {c.text};
        border: 1px solid transparent;
        border-radius: 18px;
        padding: 6px 16px;
        min-height: 36px;
        font-weight: 600;
    }}
    QPushButton:hover {{ background: {c.card}; }}
    QPushButton:pressed {{ background: {c.line}; }}
    QPushButton:disabled {{ color: {c.muted}; background: transparent; }}
    QPushButton#nav {{
        text-align: right;
        padding: 8px 14px;
        min-height: 40px;
        border-radius: 20px;
        color: {c.dim};
        font-weight: 600;
    }}
    QPushButton#nav:hover {{ background: {c.card}; color: {c.text}; }}
    QPushButton#nav:checked {{
        background: {c.nav_active_bg};
        color: {c.nav_active_fg};
    }}
    QPushButton#primary {{
        background: {c.ember};
        color: #ffffff;
        border: 1px solid {c.ember};
        border-radius: 18px;
        padding: 6px 18px;
        min-height: 36px;
        max-height: 36px;
        font-weight: 700;
    }}
    QPushButton#primary:hover {{ background: {c.ember_hot}; }}
    QPushButton#primary:pressed {{ background: #b00710; border-color: #b00710; }}
    QPushButton#ghost {{
        background: rgba(0, 0, 0, 0.35);
        color: #ffffff;
        border: 1px solid rgba(255, 255, 255, 0.45);
        border-radius: 18px;
        padding: 6px 16px;
        min-height: 36px;
        max-height: 36px;
        font-weight: 600;
    }}
    QPushButton#ghost:hover {{ background: rgba(0, 0, 0, 0.55); }}
    QPushButton#ghost:pressed {{
        background: rgba(255, 255, 255, 0.22);
        border-color: rgba(255, 255, 255, 0.7);
    }}
    QPushButton[compact="true"] {{
        padding: 0px 12px;
        font-size: 12px;
        border-radius: 14px;
        min-height: 28px;
        max-height: 28px;
    }}
    QPushButton#chip {{
        background: {c.card};
        color: {c.text};
        border: 1px solid {c.line};
        border-radius: 18px;
        padding: 0px 14px;
        min-height: 36px;
    }}
    QPushButton#chip:hover {{ border-color: {c.ember}; color: {c.ember_hot}; }}
    QPushButton#text {{
        color: {c.dim};
        padding: 4px 8px;
        font-weight: 600;
    }}
    QPushButton#text:hover {{ color: {c.ember_hot}; background: transparent; }}
    QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox {{
        background: {c.surface};
        color: {c.text};
        border: 1px solid {c.line};
        border-radius: 18px;
        padding: 8px 12px;
        selection-background-color: {c.ember};
        selection-color: #ffffff;
    }}
    QLineEdit#search {{
        background: {c.surface};
        border-radius: 18px;
        padding: 0px 14px;
        min-height: 36px;
        max-height: 36px;
        font-size: 13px;
    }}
    QLineEdit:focus, QTextEdit:focus, QComboBox:focus {{
        border: 1px solid {c.ember};
    }}
    QComboBox {{
        padding: 0px 12px;
        border-radius: 16px;
        min-height: 32px;
        max-height: 32px;
        font-size: 13px;
    }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{
        background: {c.card};
        color: {c.text};
        border: 1px solid {c.line};
        border-radius: 14px;
        selection-background-color: {c.ember};
        selection-color: #ffffff;
        padding: 2px;
        outline: none;
    }}
    QComboBox QAbstractItemView::item {{
        min-height: 26px;
        padding: 2px 8px;
        border-radius: 12px;
    }}
    QScrollArea {{ background: transparent; border: none; }}
    QWidget#canvas {{ background: transparent; }}
    QFrame#panel {{
        background: {c.bg_elev};
        border: 1px solid {c.line};
        border-radius: 22px;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 4px;
    }}
    QScrollBar::handle:vertical {{
        background: {c.line_strong};
        border-radius: 5px;
        min-height: 32px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {c.muted}; }}
    QScrollBar::add-line, QScrollBar::sub-line,
    QScrollBar::add-page, QScrollBar::sub-page {{
        background: transparent;
        height: 0;
        width: 0;
    }}
    QScrollBar:horizontal {{ height: 0; }}
    QSlider::groove:horizontal {{
        height: 4px;
        background: rgba(255, 255, 255, 0.25);
        border-radius: 2px;
    }}
    QSlider::sub-page:horizontal {{
        background: {c.ember};
        border-radius: 2px;
    }}
    QSlider::handle:horizontal {{
        width: 14px;
        height: 14px;
        margin: -6px 0;
        border-radius: 7px;
        background: #ffffff;
    }}
    QProgressBar {{
        background: {c.surface};
        border: 1px solid {c.line};
        border-radius: 8px;
        text-align: center;
        color: {c.text};
        min-height: 14px;
        max-height: 14px;
    }}
    QProgressBar::chunk {{
        background: {c.ember};
        border-radius: 7px;
    }}
    QProgressBar#downloadBar {{
        min-height: 12px;
        max-height: 12px;
        border-radius: 6px;
    }}
    QProgressBar#downloadBar::chunk {{
        border-radius: 5px;
    }}
    QToolTip {{
        background: {c.card};
        color: {c.text};
        border: 1px solid {c.line};
        border-radius: 16px;
        padding: 6px 8px;
    }}
    QDialogButtonBox QPushButton {{
        min-width: 96px;
    }}
    QMessageBox {{ background: {c.bg_elev}; }}
    QMessageBox QLabel {{ color: {c.text}; }}
    """
