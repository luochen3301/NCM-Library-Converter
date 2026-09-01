from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QGuiApplication

from ncmdump.library_db import LibraryDB
from ncmdump.models import AppSettings, TaskState
from ncmdump.ui.bridge import ApplicationBridge


class FlacMp3QmlBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def _bridge(self) -> tuple[ApplicationBridge, Path]:
        temporary = tempfile.TemporaryDirectory(prefix="ncmdump-flac-qml-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        db_path = root / "ui.sqlite3"
        db = LibraryDB(str(db_path))
        db.save_settings(AppSettings(startup_behavior="cache_only", auto_scan_on_startup=False, language="en"))
        bridge = ApplicationBridge(str(db_path))
        self.addCleanup(self._close_bridge, bridge)
        self.app.processEvents()
        return bridge, root

    def _close_bridge(self, bridge: ApplicationBridge) -> None:
        if bridge.task_controller.busy:
            bridge.cancelCurrentTask()
        deadline = 200
        while any((bridge.scan_thread, bridge.conversion_thread, bridge.flac_thread)) and deadline:
            self.app.processEvents()
            QEventLoop().processEvents()
            deadline -= 1

    @staticmethod
    def _sample(path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        rate = 44_100
        tone = np.sin(2 * np.pi * 440 * np.arange(rate // 8) / rate) * 0.25
        sf.write(path, np.column_stack((tone, tone)), rate, format="FLAC")

    def _wait_for_flac(self, bridge: ApplicationBridge) -> None:
        self.assertIsNotNone(bridge.flac_thread)
        loop = QEventLoop()
        bridge.flac_thread.finished.connect(loop.quit)
        QTimer.singleShot(10_000, loop.quit)
        loop.exec()
        self.app.processEvents()

    def test_tool_page_bridge_is_present_and_has_no_fake_queue(self) -> None:
        bridge, _root = self._bridge()
        bridge.navigate("flac_mp3")
        self.assertEqual(bridge.currentPage, "flac_mp3")
        self.assertEqual(bridge.flacCount, 0)
        self.assertFalse(bridge.canStartFlac)
        qml = (Path(__file__).resolve().parents[1] / "ncmdump" / "ui" / "qml" / "pages" / "FlacPage.qml").read_text(encoding="utf-8")
        self.assertIn("DropArea", qml)
        self.assertIn("DataTable", qml)

    def test_actual_conversion_runs_through_shared_task_state(self) -> None:
        bridge, root = self._bridge()
        source = root / "测试 sample.flac"
        self._sample(source)
        bridge.addFlacInputs([str(source)])
        bridge.startFlacConversion()
        self.assertEqual(bridge.task_controller.state, TaskState.TRANSCODING)
        self.assertFalse(bridge.canStartFlac)
        self._wait_for_flac(bridge)
        self.assertTrue(source.with_suffix(".mp3").is_file())
        self.assertEqual(bridge.task_controller.state, TaskState.IDLE)
        self.assertEqual(bridge.flacModel.get(0)["status"], "converted")
        self.assertEqual(Path(bridge.flacModel.get(0)["outputPath"]), source.with_suffix(".mp3"))

    def test_output_action_reports_missing_before_mp3_exists(self) -> None:
        bridge, root = self._bridge()
        source = root / "not-converted.flac"
        self._sample(source)
        bridge.addFlacInputs([str(source)])
        messages: list[tuple[str, str]] = []
        bridge.toastRequested.connect(lambda message, tone: messages.append((message, tone)))
        bridge.performFlacAction(0, "openOutput")
        self.assertTrue(messages)
        self.assertEqual(messages[-1][1], "error")
        self.assertFalse(source.with_suffix(".mp3").exists())

    def test_duplicate_output_preflight_preserves_previous_results(self) -> None:
        bridge, root = self._bridge()
        first = root / "disc-one" / "same-name.flac"
        second = root / "disc-two" / "same-name.flac"
        self._sample(first)
        self._sample(second)
        bridge.addFlacInputs([str(first), str(second)])
        for entry in bridge._flac_sources.values():
            actual = Path(entry["source"]).with_suffix(".mp3")
            actual.write_bytes(b"previous MP3")
            entry["completed_output"] = str(actual)
            entry["status"] = "converted"
        before = [(entry["completed_output"], entry["status"]) for entry in bridge._flac_sources.values()]
        output = root / "single-output"
        output.mkdir()
        bridge.setFlacOption("flac_mp3_output_location", "custom_folder")
        bridge.setFlacOption("flac_mp3_output_folder", str(output))
        bridge.setFlacOption("flac_mp3_preserve_structure", False)
        bridge.startFlacConversion()
        self.assertEqual(bridge.task_controller.state, TaskState.IDLE)
        self.assertIsNone(bridge.flac_worker)
        self.assertEqual(before, [(entry["completed_output"], entry["status"]) for entry in bridge._flac_sources.values()])

    def test_files_and_folders_are_deduplicated_by_bridge(self) -> None:
        bridge, root = self._bridge()
        folder = root / "Dropped Album"
        source = folder / "Disc 1" / "拖入歌曲.flac"
        self._sample(source)
        (folder / "not-a-flac.mp3").write_bytes(b"ignored")
        bridge.addFlacInputs([str(folder), str(source)])
        self.assertEqual(bridge.flacCount, 1)
        self.assertEqual(Path(bridge.flacModel.get(0)["sourcePath"]), source.resolve())

    def test_non_flac_input_is_rejected_without_queue_mutation(self) -> None:
        bridge, root = self._bridge()
        unsupported = root / "unsupported.wav"
        unsupported.write_bytes(b"not flac")
        bridge.addFlacInputs([str(unsupported)])
        self.assertEqual(bridge.flacCount, 0)
        self.assertFalse(bridge.canStartFlac)


if __name__ == "__main__":
    unittest.main()
