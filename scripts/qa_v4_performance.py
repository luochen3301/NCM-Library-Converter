from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QObject, QSize
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest

from ncmdump.desktop_app import create_engine
from ncmdump.library_db import LibraryDB, utc_now
from ncmdump.models import AppSettings, FileRecord, FileStatus


RECORD_COUNT = 4_155
PAGES = ("library", "tasks", "history", "settings", "language", "flac_mp3")


def _fixture(root: Path) -> Path:
    db_path = root / "performance.sqlite3"
    db = LibraryDB(str(db_path))
    library_path = root / "Library"
    library_path.mkdir(parents=True, exist_ok=True)
    settings = AppSettings(
        music_library_path=str(library_path),
        startup_behavior="cache_only",
        auto_scan_on_startup=False,
        language="zh_CN",
        theme="dark",
    )
    db.save_settings(settings)
    library_id = db.set_selected_library(str(library_path))
    scanned_at = utc_now()
    records = []
    for index in range(RECORD_COUNT):
        relative = f"Album {index % 97:02d}/Track {index + 1:04d}.ncm"
        status = FileStatus.FAILED.value if index % 23 == 0 else FileStatus.PENDING.value
        records.append(
            FileRecord(
                id=None,
                library_id=library_id,
                relative_path=relative,
                absolute_path=str(library_path / relative),
                file_size=4_000_000 + index,
                modified_time=1_780_000_000_000_000_000 + index,
                fingerprint=f"fixture-{index}",
                strict_hash=None,
                extension=".ncm",
                status=status,
                failure_reason="Permission denied" if status == FileStatus.FAILED.value else "",
                last_scan_at=scanned_at,
                last_seen_at=scanned_at,
            )
        )
    db.commit_scan_snapshot(
        library_id,
        records,
        (record.relative_path for record in records),
        scanned_at,
        "full",
    )
    return db_path


def main() -> int:
    output_dir = ROOT / "outputs" / "qa-v4"
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ncmdump-v4-performance-") as temp:
        db_path = _fixture(Path(temp))
        app = QGuiApplication.instance() or QGuiApplication([])

        started = time.perf_counter()
        engine, bridge = create_engine(app, db_path=str(db_path))
        QTest.qWait(260)
        initialization_ms = (time.perf_counter() - started) * 1000
        if not engine.rootObjects():
            raise RuntimeError("QML did not create a root window")
        if bridge.library_model.count != RECORD_COUNT:
            raise RuntimeError(f"Expected {RECORD_COUNT} rows, found {bridge.library_model.count}")

        window = engine.rootObjects()[0]
        window.resize(QSize(1280, 820))
        QTest.qWait(120)

        started = time.perf_counter()
        bridge.setLibrarySearch("Track 041")
        search_ms = (time.perf_counter() - started) * 1000
        if bridge.library_model.count == 0:
            raise RuntimeError("Performance search unexpectedly returned no rows")
        bridge.setLibrarySearch("")

        started = time.perf_counter()
        bridge.library_model.sortByColumn(1, True)
        sort_ms = (time.perf_counter() - started) * 1000

        started = time.perf_counter()
        for page in PAGES + PAGES:
            bridge.navigate(page)
            QTest.qWait(220)
        page_switch_ms = (time.perf_counter() - started) * 1000
        bridge.navigate("library")
        QTest.qWait(240)

        table = window.findChild(QObject, "libraryDataTable")
        if table is None:
            raise RuntimeError("Could not locate the library TableView wrapper")
        started = time.perf_counter()
        table.setProperty("contentY", max(0.0, float(table.property("contentHeight")) - float(table.property("height"))))
        QTest.qWait(140)
        scrolled = window.grabWindow()
        scroll_and_grab_ms = (time.perf_counter() - started) * 1000
        if scrolled.isNull():
            raise RuntimeError("Could not capture the 4,155-row scrolled state")
        screenshot = output_dir / "performance-4155-scroll.png"
        if not scrolled.save(str(screenshot), "PNG"):
            raise RuntimeError(f"Could not save {screenshot}")

        metrics = {
            "record_count": RECORD_COUNT,
            "initialization_ms": round(initialization_ms, 2),
            "search_ms": round(search_ms, 2),
            "sort_ms": round(sort_ms, 2),
            "twelve_animated_page_switches_ms": round(page_switch_ms, 2),
            "scroll_and_grab_ms": round(scroll_and_grab_ms, 2),
            "qml_warning_count": len(getattr(engine, "qml_warnings", [])),
            "result": "passed",
        }
        limits = {
            "initialization_ms": 5_000,
            "search_ms": 1_500,
            "sort_ms": 1_500,
            "twelve_animated_page_switches_ms": 6_000,
            "scroll_and_grab_ms": 1_500,
        }
        failures = [name for name, limit in limits.items() if metrics[name] > limit]
        if metrics["qml_warning_count"]:
            failures.append("qml_warning_count")
        if failures:
            metrics["result"] = "failed"
            metrics["failed_limits"] = failures

        report = output_dir / "performance-4155.json"
        report.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(metrics, ensure_ascii=False, indent=2))
        print(screenshot.resolve())
        print(report.resolve())
        return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
