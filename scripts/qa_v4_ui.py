from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QSize
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest

from ncmdump.desktop_app import create_engine
from ncmdump.library_db import LibraryDB
from ncmdump.library_scanner import scan_library
from ncmdump.models import AppSettings, FileStatus


PAGES = ("library", "tasks", "history", "settings", "language", "flac_mp3")


def _build_fixture(root: Path, *, empty: bool, theme: str) -> tuple[Path, Path | None]:
    db_path = root / "qa.sqlite3"
    db = LibraryDB(str(db_path))
    settings = AppSettings(
        startup_behavior="cache_only",
        auto_scan_on_startup=False,
        theme=theme,
        language="zh_CN",
        density="comfortable",
    )
    if empty:
        db.save_settings(settings)
        return db_path, None

    music = root / "音乐库 · QA"
    for album in ("01 城市夜行", "02 Quiet Signals", "03 日本語セレクション"):
        (music / album).mkdir(parents=True, exist_ok=True)
    sources: list[Path] = []
    for index in range(28):
        album = ("01 城市夜行", "02 Quiet Signals", "03 日本語セレクション")[index % 3]
        names = (
            f"{index + 1:02d} 周末夜航 · 示例歌曲.ncm",
            f"{index + 1:02d} Northern Lights Session.ncm",
            f"{index + 1:02d} 東京メモリーズ.ncm",
        )
        source = music / album / names[index % 3]
        source.write_bytes(b"NCM-QA-SOURCE")
        sources.append(source)
    (music / "02 Quiet Signals" / "Already in Library.mp3").write_bytes(b"QA-AUDIO")
    (music / "01 城市夜行" / "Archive Track.flac").write_bytes(b"fLaC" + b"\0" * 128)

    settings.music_library_path = str(music)
    db.save_settings(settings)
    scan_library(db, str(music), settings, scan_mode="full")
    records = db.list_files(db.set_selected_library(str(music)))
    for index, record in enumerate(records):
        if record.id is None or record.extension != ".ncm":
            continue
        if index % 11 == 0:
            db.update_file_status(record.id, FileStatus.FAILED.value, failure_reason="No permission to write the output file.")
        elif index % 7 == 0:
            db.update_file_status(record.id, FileStatus.FAILED.value, failure_reason="The output folder is unavailable.")
        elif index % 5 == 0:
            output = Path(record.absolute_path).with_suffix(".flac")
            output.write_bytes(b"fLaC" + b"\0" * 256)
            db.update_file_status(record.id, FileStatus.CONVERTED.value, output_path=str(output))
            db.add_history(record.id, record.library_id, record.absolute_path, str(output), record.fingerprint, "success", duration_ms=1840 + index * 37)
        elif index % 13 == 0:
            db.mark_ignored([record.id], True)
    failed = db.list_files(records[0].library_id, status=FileStatus.FAILED.value)
    for record in failed:
        db.add_history(record.id, record.library_id, record.absolute_path, "", record.fingerprint, "failed", record.failure_reason, 720)
    db.add_log("INFO", "qa", "V4 visual fixture loaded")
    db.add_log("WARNING", "scan", "Example watcher message for layout verification")

    flac = root / "FLAC Queue" / "现场录音 · Demo.flac"
    flac.parent.mkdir()
    flac.write_bytes(b"fLaC" + b"\0" * 512)
    return db_path, flac


def capture(output_dir: Path, width: int, height: int, label: str, *, empty: bool, theme: str) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ncmdump-v4-visual-") as temp:
        db_path, flac = _build_fixture(Path(temp), empty=empty, theme=theme)
        app = QGuiApplication.instance() or QGuiApplication([])
        engine, bridge = create_engine(app, db_path=str(db_path))
        QTest.qWait(120)
        if not engine.rootObjects():
            raise RuntimeError("QML did not create a root window")
        window = engine.rootObjects()[0]
        window.resize(QSize(width, height))
        QTest.qWait(100)
        if flac is not None:
            source = str(flac.resolve())
            key = os.path.normcase(source)
            bridge._flac_sources[key] = {
                "key": key,
                "source": source,
                "root": str(flac.parent.resolve()),
                "output": str(flac.with_suffix(".mp3")),
                "completed_output": "",
                "status": "waiting",
                "size": flac.stat().st_size,
                "error": "",
                "progress": 0.0,
            }
            bridge._refresh_flac_model()
        if bridge.library_model.count >= 4:
            bridge.library_model.toggleChecked(1)
            bridge.library_model.toggleChecked(3)

        pages = ("library",) if empty else PAGES
        written: list[Path] = []
        for page in pages:
            bridge.navigate(page)
            QTest.qWait(280)
            image = window.grabWindow()
            if image.isNull():
                raise RuntimeError(f"Could not capture {page}")
            suffix = "empty" if empty else page
            target = output_dir / f"{label}-{width}x{height}-{suffix}.png"
            if not image.save(str(target), "PNG"):
                raise RuntimeError(f"Could not save {target}")
            written.append(target)
        warnings = list(getattr(engine, "qml_warnings", []))
        window.setVisible(False)
        window.deleteLater()
        engine.deleteLater()
        QTest.qWait(20)
        if warnings:
            raise RuntimeError("QML warnings:\n" + "\n".join(warnings))
        return written


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render deterministic NCM Converter V4 QML QA states.")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs" / "qa-v4")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=820)
    parser.add_argument("--label", default="100pct")
    parser.add_argument("--empty", action="store_true")
    parser.add_argument("--theme", choices=("dark", "light"), default="dark")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    paths = capture(args.output_dir, args.width, args.height, args.label, empty=args.empty, theme=args.theme)
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
