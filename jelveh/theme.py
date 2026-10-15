"""Colors taken from jelveh.top (jet / ember / gold / mint) and Vazirmatn."""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPixmap

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
        border: none;
        border-radius: 12px;
        padding: 8px 14px;
        font-weight: 600;
    }}
    QPushButton:hover {{ background: {c.card}; }}
    QPushButton:disabled {{ color: {c.muted}; background: transparent; }}
    QPushButton#nav {{
        text-align: right;
        padding: 10px 14px;
        border-radius: 14px;
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
        border-radius: 999px;
        padding: 10px 20px;
        font-weight: 700;
    }}
    QPushButton#primary:hover {{ background: {c.ember_hot}; }}
    QPushButton#ghost {{
        background: rgba(0, 0, 0, 0.35);
        color: #ffffff;
        border: 1px solid rgba(255, 255, 255, 0.45);
        border-radius: 999px;
        padding: 10px 18px;
        font-weight: 600;
    }}
    QPushButton#ghost:hover {{ background: rgba(0, 0, 0, 0.55); }}
    QPushButton#chip {{
        background: {c.card};
        color: {c.text};
        border: 1px solid {c.line};
        border-radius: 999px;
        padding: 6px 12px;
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
        border-radius: 12px;
        padding: 8px 12px;
        selection-background-color: {c.ember};
        selection-color: #ffffff;
    }}
    QLineEdit#search {{
        background: {c.surface};
        border-radius: 999px;
        padding: 9px 16px;
        min-height: 20px;
    }}
    QLineEdit:focus, QTextEdit:focus, QComboBox:focus {{
        border: 1px solid {c.ember};
    }}
    QComboBox::drop-down {{ border: none; width: 24px; }}
    QComboBox QAbstractItemView {{
        background: {c.card};
        color: {c.text};
        border: 1px solid {c.line};
        selection-background-color: {c.ember};
        selection-color: #ffffff;
        padding: 4px;
    }}
    QScrollArea {{ background: transparent; border: none; }}
    QWidget#canvas {{ background: transparent; }}
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
    QToolTip {{
        background: {c.card};
        color: {c.text};
        border: 1px solid {c.line};
        padding: 6px 8px;
    }}
    QMessageBox {{ background: {c.bg_elev}; }}
    QMessageBox QLabel {{ color: {c.text}; }}
    """
