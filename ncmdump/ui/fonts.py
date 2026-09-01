from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase


_APPLICATION_FONT_IDS: list[int] = []


def _platform_font_files() -> tuple[Path, ...]:
    if sys.platform.startswith("win"):
        fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        return (
            fonts / "msyh.ttc",
            fonts / "msyhl.ttc",
            fonts / "simsun.ttc",
        )
    if sys.platform == "darwin":
        return (
            Path("/System/Library/Fonts/PingFang.ttc"),
            Path("/System/Library/Fonts/STHeiti Medium.ttc"),
        )
    return (
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf"),
        Path("/usr/share/fonts/opentype/source-han-sans/SourceHanSansSC-Regular.otf"),
    )


def install_ui_font(point_size: int = 10) -> QFont:
    """Register a local CJK-capable system font and return one UI font.

    Some Qt offscreen and packaged environments do not enumerate Windows font
    fallback families even though the files exist. Registering the local
    system font fixes Chinese text without redistributing a proprietary font.
    """

    preferred = (
        "Segoe UI Variable",
        "Microsoft YaHei UI",
        "Microsoft YaHei",
        "PingFang SC",
        "Noto Sans CJK SC",
        "Source Han Sans SC",
        "Segoe UI",
        "Arial",
    )
    families = set(QFontDatabase.families())
    if not any(family in families for family in preferred[:6]):
        for path in _platform_font_files():
            if not path.is_file():
                continue
            font_id = QFontDatabase.addApplicationFont(str(path))
            if font_id >= 0:
                _APPLICATION_FONT_IDS.append(font_id)
                families.update(QFontDatabase.applicationFontFamilies(font_id))
                if any(family in families for family in preferred[:6]):
                    break

    family = next((candidate for candidate in preferred if candidate in families), "Segoe UI")
    font = QFont(family, point_size)
    font.setFamilies(list(preferred))
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return font


__all__ = ["install_ui_font"]
