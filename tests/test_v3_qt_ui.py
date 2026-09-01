from __future__ import annotations

import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtGui import QGuiApplication

from ncmdump.desktop_app import create_engine
from ncmdump.library_db import LibraryDB
from ncmdump.library_scanner import scan_library
from ncmdump.models import AppSettings, FileStatus, QueueProgress, TaskState
from ncmdump.ui.bridge import ApplicationBridge


ROOT = Path(__file__).resolve().parents[1]
QML_ROOT = ROOT / "ncmdump" / "ui" / "qml"


class V4QmlInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QGuiApplication.instance() or QGuiApplication([])
        cls.qml_temp = tempfile.TemporaryDirectory(prefix="ncmdump-v4-qml-engine-")
        db_path = Path(cls.qml_temp.name) / "qml.sqlite3"
        db = LibraryDB(str(db_path))
        db.save_settings(AppSettings(startup_behavior="cache_only", auto_scan_on_startup=False, language="en"))
        cls.engine, cls.qml_bridge = create_engine(cls.app, db_path=str(db_path))
        for _ in range(4):
            cls.app.processEvents()

    @classmethod
    def tearDownClass(cls) -> None:
        for root in cls.engine.rootObjects():
            root.close()
        cls.app.processEvents()
        cls.qml_temp.cleanup()

    def _bridge(self, *, populated: bool = True) -> ApplicationBridge:
        temporary = tempfile.TemporaryDirectory(prefix="ncmdump-v4-bridge-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        db_path = root / "ui.sqlite3"
        db = LibraryDB(str(db_path))
        settings = AppSettings(startup_behavior="cache_only", auto_scan_on_startup=False, theme="dark", language="en")
        if populated:
            music = root / "A long bilingual music library 音乐库"
            music.mkdir()
            for index in range(12):
                (music / f"Track {index + 1:02d} - 示例歌曲.ncm").write_bytes(b"source")
            settings.music_library_path = str(music)
            scan_library(db, str(music), settings, scan_mode="full")
        db.save_settings(settings)
        bridge = ApplicationBridge(str(db_path))
        self.app.processEvents()
        bridge.refreshAll()
        return bridge

    def test_all_qml_pages_load_without_warnings(self) -> None:
        self.assertEqual(len(self.engine.rootObjects()), 1)
        self.assertEqual(getattr(self.engine, "qml_warnings", []), [])
        for page in ("library", "tasks", "history", "settings", "language", "flac_mp3"):
            self.qml_bridge.navigate(page)
            self.app.processEvents()
            self.assertEqual(self.qml_bridge.currentPage, page)
        self.assertEqual(getattr(self.engine, "qml_warnings", []), [])

    def test_checked_ids_are_separate_from_visual_row_selection(self) -> None:
        bridge = self._bridge()
        first = bridge.libraryModel.get(0)
        self.assertEqual(bridge.libraryModel.checkedCount, 0)
        bridge.libraryModel.toggleChecked(0)
        self.assertEqual(bridge.libraryModel.checked_ids, {first["recordId"]})

    def test_checked_ids_survive_search_and_status_filtering(self) -> None:
        bridge = self._bridge()
        selected = bridge.libraryModel.get(0)
        bridge.libraryModel.toggleChecked(0)
        bridge.setLibrarySearch("does-not-match")
        self.assertEqual(bridge.libraryModel.count, 0)
        self.assertIn(selected["recordId"], bridge.libraryModel.checked_ids)
        bridge.resetLibraryFilters()
        self.assertIn(selected["recordId"], bridge.libraryModel.checked_ids)

    def test_convert_checked_uses_only_checked_convertible_ids(self) -> None:
        bridge = self._bridge()
        first = bridge.libraryModel.get(0)
        bridge.libraryModel.toggleChecked(0)
        with patch.object(bridge, "_start_conversion") as start:
            bridge.convertChecked()
        start.assert_called_once_with([first["recordId"]])
        self.assertIn(first["recordId"], bridge.libraryModel.checked_ids)

    def test_terminal_conversion_clears_checked_ids_for_all_outcomes(self) -> None:
        outcomes = (
            QueueProgress(total=1, completed=1, converted=1, overall_percent=100),
            QueueProgress(total=1, completed=1, skipped=1, overall_percent=100),
            QueueProgress(total=1, completed=1, failed=1, overall_percent=100),
            QueueProgress(total=1, not_processed=1, remaining=1, canceled=True),
        )
        for progress in outcomes:
            with self.subTest(progress=progress):
                bridge = self._bridge()
                bridge.libraryModel.toggleChecked(0)
                bridge.queueModel.checked_ids.update(bridge.libraryModel.checked_ids)
                bridge._on_conversion_finished(progress)
                self.assertEqual(bridge.libraryModel.checked_ids, set())
                self.assertEqual(bridge.queueModel.checked_ids, set())

    def test_worker_failure_is_terminal_and_clears_batch(self) -> None:
        bridge = self._bridge()
        bridge.libraryModel.toggleChecked(0)
        bridge.queueModel.checked_ids.update(bridge.libraryModel.checked_ids)
        bridge._on_conversion_failed("worker failed")
        self.assertEqual(bridge.libraryModel.checked_ids, set())
        self.assertEqual(bridge.queueModel.checked_ids, set())

    def test_cancel_request_keeps_batch_until_terminal_result(self) -> None:
        bridge = self._bridge()
        bridge.libraryModel.toggleChecked(0)
        checked = set(bridge.libraryModel.checked_ids)
        bridge.conversion_worker = MagicMock()
        bridge.task_controller.begin_conversion()
        bridge.cancelCurrentTask()
        self.assertEqual(bridge.libraryModel.checked_ids, checked)
        bridge._on_conversion_finished(QueueProgress(total=1, not_processed=1, remaining=1, canceled=True))
        self.assertEqual(bridge.libraryModel.checked_ids, set())
        bridge.conversion_worker = None
        bridge.task_controller.finish()

    def test_switching_library_clears_old_checked_ids(self) -> None:
        bridge = self._bridge()
        bridge.libraryModel.toggleChecked(0)
        with tempfile.TemporaryDirectory(prefix="ncmdump-v4-second-") as second:
            bridge._activate_library(second, clear_checked=True)
        self.assertEqual(bridge.libraryModel.checked_ids, set())
        self.assertEqual(bridge.queueModel.checked_ids, set())

    def test_nonconvertible_checked_rows_do_not_enable_batch_convert(self) -> None:
        bridge = self._bridge()
        record_id = bridge.libraryModel.get(0)["recordId"]
        bridge.db.update_file_status(record_id, FileStatus.NORMAL.value)
        bridge.refreshAll()
        bridge.libraryModel.toggleChecked(0)
        self.assertFalse(bridge.canConvertChecked)

    def test_pending_or_failed_checked_rows_enable_batch_convert(self) -> None:
        for status in (FileStatus.PENDING.value, FileStatus.FAILED.value):
            with self.subTest(status=status):
                bridge = self._bridge()
                record_id = bridge.libraryModel.get(0)["recordId"]
                bridge.db.update_file_status(record_id, status)
                bridge.refreshAll()
                bridge.libraryModel.toggleChecked(0)
                self.assertTrue(bridge.canConvertChecked)

    def test_default_library_columns_fit_1280_content_lane(self) -> None:
        source = (QML_ROOT / "pages" / "LibraryPage.qml").read_text(encoding="utf-8")
        widths = [int(value) for value in re.findall(r"width: (\d+),", source[source.index("columns: ["):])[:8]]
        self.assertEqual(len(widths), 8)
        self.assertLessEqual(sum(widths), 1036)
        table = (QML_ROOT / "components" / "DataTable.qml").read_text(encoding="utf-8")
        self.assertIn("root.totalColumnWidth() > root.width - 2", table)

    def test_empty_library_never_enables_convert_all(self) -> None:
        bridge = self._bridge(populated=False)
        self.assertFalse(bridge.hasLibrary)
        self.assertFalse(bridge.canConvertPending)
        self.assertEqual(bridge.libraryModel.count, 0)

    def test_shared_task_controller_prevents_overlapping_operations(self) -> None:
        bridge = self._bridge()
        bridge.task_controller.begin_scan()
        with self.assertRaises(Exception):
            bridge.task_controller.begin_conversion()
        bridge.task_controller.finish()
        bridge.task_controller.begin_transcode()
        self.assertEqual(bridge.taskState, TaskState.TRANSCODING.value)
        bridge.task_controller.finish()

    def test_setting_changes_emit_property_notifications(self) -> None:
        bridge = self._bridge(populated=False)
        events: list[str] = []
        bridge.stateChanged.connect(lambda: events.append("state"))
        bridge.themeChanged.connect(lambda: events.append("theme"))
        bridge.setSetting("theme", "light")
        self.assertIn("theme", events)
        self.assertIn("state", events)
        self.assertTrue(bridge.settingsDirty)

    def test_language_changes_are_immediate_and_revisioned(self) -> None:
        bridge = self._bridge(populated=False)
        revision = bridge.i18nRevision
        events: list[bool] = []
        bridge.languageChanged.connect(lambda: events.append(True))
        bridge.setSetting("language", "zh_CN")
        self.assertGreater(bridge.i18nRevision, revision)
        self.assertTrue(events)
        self.assertEqual(bridge.translate("nav.library"), "音乐库")

    def test_confirmation_token_routes_only_the_matching_response(self) -> None:
        bridge = self._bridge()
        requests: list[str] = []
        bridge.confirmationRequested.connect(lambda token, *_args: requests.append(token))
        with patch.object(bridge, "startScan") as scan:
            bridge.requestFullScan()
            self.assertEqual(len(requests), 1)
            bridge.respondToConfirmation("not-the-token", True)
            scan.assert_not_called()
            bridge.respondToConfirmation(requests[0], True)
            scan.assert_called_once_with("full", False)

    def test_request_close_cancels_worker_before_allowing_window_close(self) -> None:
        bridge = self._bridge()
        bridge.task_controller.begin_scan()
        bridge.scan_worker = MagicMock()
        self.assertFalse(bridge.requestClose())
        bridge.scan_worker.cancel.assert_called_once()
        self.assertFalse(bridge.allowClose)
        bridge.scan_worker = None
        bridge.task_controller.finish()

    def test_runtime_contains_no_pyqt_widgets_or_fake_state(self) -> None:
        desktop = (ROOT / "ncmdump" / "desktop_app.py").read_text(encoding="utf-8")
        bridge = (ROOT / "ncmdump" / "ui" / "bridge.py").read_text(encoding="utf-8")
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertNotIn("PyQt6", desktop + bridge + requirements)
        self.assertNotIn("qtawesome", requirements)
        self.assertIn("QGuiApplication", desktop)
        self.assertIn("QQmlApplicationEngine", desktop)
        self.assertTrue((QML_ROOT / "assets" / "icons" / "LUCIDE_LICENSE.txt").is_file())


if __name__ == "__main__":
    unittest.main()
