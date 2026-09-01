from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        Path("C:/Windows/Fonts/segoeuib.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf"),
    )
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def create_comparison(source_path: Path, implementation_path: Path, output_path: Path) -> None:
    with Image.open(source_path) as source_image, Image.open(implementation_path) as implementation_image:
        source = source_image.convert("RGB")
        implementation = implementation_image.convert("RGB")
        header_height = 52
        gutter = 16
        panel_width = max(source.width, implementation.width)
        panel_height = max(source.height, implementation.height)
        canvas = Image.new("RGB", (panel_width * 2 + gutter, panel_height + header_height), "#080d13")
        draw = ImageDraw.Draw(canvas)
        font = _font(20)
        draw.text((16, 14), "SOURCE V3 - 1280 x 820 - SELECTED LIBRARY", font=font, fill="#dce4ec")
        draw.text((panel_width + gutter + 16, 14), "IMPLEMENTATION V4 - 1280 x 820 - SELECTED LIBRARY", font=font, fill="#36d1c4")
        canvas.paste(source, (0, header_height))
        canvas.paste(implementation, (panel_width + gutter, header_height))
        draw.rectangle((panel_width, header_height, panel_width + gutter - 1, panel_height + header_height), fill="#26313d")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(output_path, "PNG", optimize=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Place a source screenshot and implementation screenshot in one QA image.")
    parser.add_argument("source", type=Path)
    parser.add_argument("implementation", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    create_comparison(args.source, args.implementation, args.output)
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
