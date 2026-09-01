from __future__ import annotations

from pathlib import Path

from PIL import Image
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "ncmdump" / "ui" / "qml" / "assets" / "icons" / "music-2-dark.svg"
PNG_TARGETS = (
    ROOT / "file" / "ncm-converter-v4.png",
    ROOT / "ncmdump" / "ui" / "assets" / "app-icon.png",
)
ICO_TARGET = ROOT / "file" / "ncm-converter-v4.ico"


def render_icon(size: int = 512) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("transparent"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(QColor("transparent"))
    painter.setBrush(QColor("#28C7B7"))
    inset = size * 0.055
    painter.drawRoundedRect(QRectF(inset, inset, size - inset * 2, size - inset * 2), size * 0.22, size * 0.22)
    renderer = QSvgRenderer(str(SOURCE))
    icon_inset = size * 0.245
    renderer.render(painter, QRectF(icon_inset, icon_inset, size - icon_inset * 2, size - icon_inset * 2))
    painter.end()
    return image


def main() -> int:
    _app = QGuiApplication.instance() or QGuiApplication([])
    if not SOURCE.is_file():
        raise FileNotFoundError(SOURCE)
    image = render_icon()
    for target in PNG_TARGETS:
        target.parent.mkdir(parents=True, exist_ok=True)
        if not image.save(str(target), "PNG"):
            raise RuntimeError(f"Could not save {target}")
    with Image.open(PNG_TARGETS[0]) as png:
        png.save(ICO_TARGET, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
