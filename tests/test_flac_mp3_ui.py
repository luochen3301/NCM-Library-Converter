from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QEventLoop, QMimeData, QPoint, QPointF, QRect, QTimer, QUrl, Qt
from PyQt6.QtGui import QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import QApplication

from gui import MainWindow
from ncmdump.library_db import LibraryDB
from ncmdump.models import AppSettings, TaskState


class FlacMp3QtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self) -> tuple[MainWindow, Path]:
        temporary = tempfile.TemporaryDirectory(prefix="ncmdump-flac-qt-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        os.environ["NCMDUMP_DB_PATH"] = str(root / "ui.sqlite3")
        db = LibraryDB(str(root / "ui.sqlite3"))
        db.save_settings(AppSettings(startup_behavior="cache_only", auto_scan_on_startup=False, language="en"))
        window = MainWindow()
        window.resize(960, 620)
        window.sidebar.setCurrentRow(window.sidebar_nav_keys.index("flac_mp3"))
        window.show()
        self.app.processEvents()
        self.addCleanup(self._close_window, window)
        return window, root

    def _close_window(self, window: MainWindow) -> None:
        if window.flac_worker:
            window.flac_worker.cancel()
        window.close()
        self.app.processEvents()

    @staticmethod
    def _sample(path: Path) -> None:
        rate = 44_100
        tone = np.sin(2 * np.pi * 440 * np.arange(rate // 4) / rate) * 0.25
        sf.write(path, np.column_stack((tone, tone)), rate, format="FLAC")

    def test_tool_page_is_present_and_controls_stay_inside_960_layout(self):
        window, _root = self._window()
        self.assertEqual(window.pages.currentIndex(), window._page_indices["flac_mp3"])
        self.assertFalse(window.top_bar.isVisibleTo(window))
        self.assertFalse(window.progress_panel.isVisibleTo(window))
        self.assertFalse(window.flac_start_button.isEnabled())
        self.assertFalse(window.flac_cancel_button.isVisible())
        page_rect = window.pages.currentWidget().rect()
        for widget in (
            window.flac_title,
            window.flac_output_mode,
            window.flac_bitrate_combo,
            window.flac_preserve_switch,
            window.flac_skip_switch,
            window.flac_table,
            window.flac_start_button,
        ):
            top_left = widget.mapTo(window.pages.currentWidget(), QPoint(0, 0))
            rect = QRect(top_left, widget.size())
            self.assertTrue(page_rect.contains(rect), (widget.objectName(), page_rect, rect))

        self.assertLessEqual(
            window.flac_preserve_switch.geometry().right(),
            window.flac_skip_switch.geometry().left(),
        )
        self.assertEqual(window.flac_custom_output.isEnabled(), False)

        window.sidebar.setCurrentRow(window.sidebar_nav_keys.index("library"))
        self.app.processEvents()
        self.assertTrue(window.top_bar.isVisibleTo(window))
        self.assertTrue(window.progress_panel.isVisibleTo(window))

    def test_actual_conversion_runs_through_shared_task_state(self):
        window, root = self._window()
        source = root / "测试 sample.flac"
        self._sample(source)
        window._register_flac_sources([str(source)], str(root))
        self.assertTrue(window.flac_start_button.isEnabled())

        window._start_flac_conversion()
        self.assertEqual(window.task_controller.state, TaskState.TRANSCODING)
        self.assertFalse(window.rescan_button.isEnabled())
        self.assertFalse(window.flac_start_button.isEnabled())

        loop = QEventLoop()
        window.flac_thread.finished.connect(loop.quit)
        QTimer.singleShot(10_000, loop.quit)
        loop.exec()
        self.app.processEvents()

        self.assertTrue(source.with_suffix(".mp3").is_file())
        self.assertEqual(window.task_controller.state, TaskState.IDLE)
        self.assertEqual(next(iter(window.flac_sources.values()))["status"], "converted")
        self.assertIn("complete", window.flac_status_label.text().lower())

        entry = next(iter(window.flac_sources.values()))
        actual_output = str(source.with_suffix(".mp3").resolve())
        self.assertEqual(window._flac_output_candidate(entry), actual_output)

        # Changing the next job's output settings must not lose the actual
        # result path used by the post-conversion context menu.
        alternate = root / "alternate-output"
        alternate.mkdir()
        window.flac_output_mode.setCurrentIndex(window.flac_output_mode.findData("custom_folder"))
        window.flac_custom_output.setText(str(alternate))
        self.app.processEvents()
        self.assertEqual(window._flac_output_candidate(entry), actual_output)

        menu = window._build_flac_context_menu(entry)
        reveal_action = next(action for action in menu.actions() if action.objectName() == "flacRevealOutputAction")
        self.assertTrue(reveal_action.isEnabled())
        first_item = window.flac_table.item(0, 0)
        context_point = window.flac_table.visualItemRect(first_item).center()
        with (
            patch.object(window, "_build_flac_context_menu", return_value=menu),
            patch.object(menu, "exec", return_value=reveal_action),
            patch.object(window, "_reveal_path", return_value=True) as reveal,
        ):
            window._show_flac_context_menu(context_point)
        reveal.assert_called_once_with(actual_output)

    def test_context_menu_disables_output_actions_before_mp3_exists(self):
        window, root = self._window()
        source = root / "not-converted.flac"
        self._sample(source)
        window._register_flac_sources([str(source)], str(root))

        menu = window._build_flac_context_menu(next(iter(window.flac_sources.values())))
        actions = {action.objectName(): action for action in menu.actions() if action.objectName()}
        self.assertFalse(actions["flacRevealOutputAction"].isEnabled())
        self.assertFalse(actions["flacOpenOutputAction"].isEnabled())

        window.flac_table.setCurrentCell(0, 0)
        blank_point = QPoint(4, window.flac_table.viewport().height() - 2)
        with patch.object(window, "_build_flac_context_menu") as build_menu:
            window._show_flac_context_menu(blank_point)
        build_menu.assert_not_called()

    def test_duplicate_output_preflight_preserves_previous_results(self):
        window, root = self._window()
        first = root / "disc-one" / "same-name.flac"
        second = root / "disc-two" / "same-name.flac"
        first.parent.mkdir()
        second.parent.mkdir()
        self._sample(first)
        self._sample(second)
        window._register_flac_sources([str(first), str(second)], str(root))

        for entry in window.flac_sources.values():
            actual_output = Path(entry["source"]).with_suffix(".mp3")
            actual_output.write_bytes(b"previous MP3")
            entry["output"] = str(actual_output)
            entry["completed_output"] = str(actual_output)
            entry["status"] = "converted"
        previous = {
            key: (entry["completed_output"], entry["status"])
            for key, entry in window.flac_sources.items()
        }

        custom = root / "single-output"
        custom.mkdir()
        window.flac_output_mode.setCurrentIndex(window.flac_output_mode.findData("custom_folder"))
        window.flac_custom_output.setText(str(custom))
        window.flac_preserve_switch.setChecked(False)
        window._start_flac_conversion()

        self.assertEqual(window.task_controller.state, TaskState.IDLE)
        self.assertIsNone(window.flac_worker)
        self.assertEqual(
            previous,
            {
                key: (entry["completed_output"], entry["status"])
                for key, entry in window.flac_sources.items()
            },
        )

    def test_files_and_folders_can_be_dropped_anywhere_on_tool_page(self):
        window, root = self._window()
        folder = root / "Dropped Album"
        nested = folder / "Disc 1"
        nested.mkdir(parents=True)
        source = nested / "拖入歌曲.flac"
        self._sample(source)
        ignored = folder / "not-a-flac.mp3"
        ignored.write_bytes(b"ignored")
        page = window.flac_drop_page
        baseline_table_geometry = window.flac_table.geometry()

        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(folder)), QUrl.fromLocalFile(str(ignored))])
        enter = QDragEnterEvent(
            QPoint(20, 20),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(page, enter)
        self.app.processEvents()
        self.assertTrue(enter.isAccepted())
        self.assertTrue(page.drop_overlay.isVisibleTo(page))

        drop = QDropEvent(
            QPointF(20, 20),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(page, drop)
        self.app.processEvents()

        self.assertTrue(drop.isAccepted())
        self.assertFalse(page.drop_overlay.isVisible())
        self.assertEqual(window.flac_table.rowCount(), 1)
        self.assertEqual(Path(next(iter(window.flac_sources.values()))["source"]), source.resolve())
        self.assertEqual(window.flac_table.geometry(), baseline_table_geometry)

        # Dropping the same file again is accepted but remains de-duplicated.
        duplicate_mime = QMimeData()
        duplicate_mime.setUrls([QUrl.fromLocalFile(str(source))])
        duplicate_enter = QDragEnterEvent(
            QPoint(30, 30),
            Qt.DropAction.CopyAction,
            duplicate_mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(page, duplicate_enter)
        duplicate_drop = QDropEvent(
            QPointF(30, 30),
            Qt.DropAction.CopyAction,
            duplicate_mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(page, duplicate_drop)
        self.app.processEvents()
        self.assertTrue(duplicate_drop.isAccepted())
        self.assertEqual(window.flac_table.rowCount(), 1)

    def test_non_flac_drop_is_rejected_without_showing_overlay(self):
        window, root = self._window()
        unsupported = root / "unsupported.wav"
        unsupported.write_bytes(b"not flac")
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(unsupported))])
        enter = QDragEnterEvent(
            QPoint(20, 20),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

        QApplication.sendEvent(window.flac_drop_page, enter)
        self.app.processEvents()

        self.assertFalse(enter.isAccepted())
        self.assertFalse(window.flac_drop_page.drop_overlay.isVisible())
        self.assertEqual(window.flac_table.rowCount(), 0)


if __name__ == "__main__":
    unittest.main()
