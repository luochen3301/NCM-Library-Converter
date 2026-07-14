from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtWidgets import QApplication

from gui import MainWindow
from ncmdump.desktop_app import (
    LIBRARY_ACTION_CONTROL_HEIGHT,
    LIBRARY_ACTION_RADIUS,
    LIBRARY_ACTION_ROW_GAP,
    LIBRARY_ACTION_SLOT_HEIGHT,
)
from ncmdump.library_db import LibraryDB
from ncmdump.library_scanner import scan_library
from ncmdump.models import AppSettings, FileStatus, QueueProgress


class V3QtInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self, *, populated: bool = True) -> MainWindow:
        temporary = tempfile.TemporaryDirectory(prefix="ncmdump-v3-qt-test-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        db_path = root / "ui.sqlite3"
        os.environ["NCMDUMP_DB_PATH"] = str(db_path)
        db = LibraryDB(str(db_path))
        settings = AppSettings(
            startup_behavior="cache_only",
            auto_scan_on_startup=False,
            theme="dark",
            language="en",
        )
        if populated:
            music = root / "A long bilingual music library 音乐库"
            music.mkdir()
            for index in range(12):
                (music / f"Track {index + 1:02d} - 示例歌曲.ncm").write_bytes(b"source")
            settings.music_library_path = str(music)
            scan_library(db, str(music), settings, scan_mode="full")
        db.save_settings(settings)

        window = MainWindow()
        window.resize(960, 620)
        window.show()
        for _ in range(3):
            self.app.processEvents()
        self.addCleanup(self._close_window, window)
        return window

    def _close_window(self, window: MainWindow) -> None:
        window.close()
        self.app.processEvents()

    def test_fixed_slots_prevent_selection_progress_and_page_jump(self):
        window = self._window()
        self.assertEqual(window.findChild(type(window.progress_panel), "taskStrip").height(), 66)
        self.assertEqual(window.library_action_slot.height(), LIBRARY_ACTION_SLOT_HEIGHT)
        self.assertFalse(window.result_count_label.wordWrap())
        baseline = window.file_table.mapTo(window, QPoint(0, 0)).y()

        window.file_model.toggle_row_checked(0, True)
        self.app.processEvents()
        selected = window.file_table.mapTo(window, QPoint(0, 0)).y()
        search_target = window.file_model.record_at(window.file_model.rowCount() - 1)
        window.search_input.setText(Path(search_target.relative_path).name)
        self.app.processEvents()
        searched = window.file_table.mapTo(window, QPoint(0, 0)).y()
        window.search_input.clear()
        self.app.processEvents()
        window.progress_panel.set_progress(57, "Converting", "A very long file name.ncm", "7 of 12")
        self.app.processEvents()
        progressing = window.file_table.mapTo(window, QPoint(0, 0)).y()
        window.sidebar.setCurrentRow(window.sidebar_nav_keys.index("tasks"))
        self.app.processEvents()
        window.sidebar.setCurrentRow(window.sidebar_nav_keys.index("library"))
        self.app.processEvents()
        returned = window.file_table.mapTo(window, QPoint(0, 0)).y()

        self.assertLessEqual(abs(selected - baseline), 1)
        self.assertLessEqual(abs(searched - baseline), 1)
        self.assertLessEqual(abs(progressing - baseline), 1)
        self.assertLessEqual(abs(returned - baseline), 1)

    def test_task_strip_text_and_actions_use_stable_non_overlapping_lanes(self):
        window = self._window()
        strip = window.progress_panel

        def rect_in_strip(widget):
            return QRect(widget.mapTo(strip, QPoint(0, 0)), widget.size())

        def snapshot():
            title = rect_in_strip(strip.title_label)
            detail = rect_in_strip(strip.detail_label)
            metrics = rect_in_strip(strip.metrics_label)
            actions = rect_in_strip(strip.action_host)
            progress = rect_in_strip(strip.progress_bar)
            self.assertLess(title.right(), detail.left())
            self.assertLess(detail.right(), metrics.left())
            self.assertLess(metrics.right(), actions.left())
            self.assertGreater(progress.top(), max(title.bottom(), detail.bottom(), metrics.bottom(), actions.bottom()))
            return tuple((rect.x(), rect.y(), rect.width(), rect.height()) for rect in (title, detail, metrics, actions))

        strip.set_idle("Cached library loaded", "Showing the last saved index.")
        self.app.processEvents()
        idle_geometry = snapshot()

        strip.set_busy(
            "Scanning library",
            "A very long folder path that must be elided without entering the metrics lane",
            "Indexed 123,456 files",
        )
        strip.set_actions(True, can_pause=False)
        self.app.processEvents()
        busy_geometry = snapshot()

        metrics = "Converted 9,999 | Failed 1,234 | Remaining 88,888"
        strip.set_progress(
            73,
            "Converting files",
            "A very long current file name that must stay inside the detail lane.ncm",
            metrics,
        )
        strip.set_actions(True, paused=False)
        self.app.processEvents()
        progress_geometry = snapshot()

        self.assertEqual(idle_geometry, busy_geometry)
        self.assertEqual(idle_geometry, progress_geometry)
        self.assertEqual(strip.metrics_label.fullText(), metrics)
        self.assertEqual(strip.metrics_label.toolTip(), metrics)

    def test_scrollbars_use_complete_theme_styling_without_native_page_artifacts(self):
        window = self._window()
        style = window.styleSheet()
        for selector in (
            "QScrollBar:vertical",
            "QScrollBar::handle:vertical",
            "QScrollBar::handle:vertical:hover",
            "QScrollBar::handle:vertical:pressed",
            "QScrollBar::handle:vertical:disabled",
            "QScrollBar:horizontal",
            "QScrollBar::handle:horizontal",
            "QScrollBar::add-page:vertical",
            "QScrollBar::sub-page:horizontal",
            "QAbstractScrollArea::corner",
        ):
            self.assertIn(selector, style)

        self.assertEqual(window.file_table.verticalScrollBar().width(), 14)
        self.assertEqual(window.file_table.horizontalScrollBar().height(), 14)
        self.assertEqual(
            window.sidebar.horizontalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
        )

    def test_checked_ids_are_the_only_batch_selection_source(self):
        window = self._window()
        window.file_table.selectRow(0)
        self.app.processEvents()
        self.assertEqual(window._selected_records(window.file_table, window.file_model), [])

        expected = window.file_model.record_at(0)
        window.file_model.toggle_row_checked(0, True)
        selected = window._selected_records(window.file_table, window.file_model)
        self.assertEqual([record.id for record in selected], [expected.id])

    def test_starting_conversion_keeps_checked_batch_until_terminal_result(self):
        window = self._window()
        record = window.file_model.record_at(0)
        window.file_model.toggle_row_checked(0, True)

        try:
            with (
                patch("ncmdump.desktop_app.QThread"),
                patch("ncmdump.desktop_app.ConversionWorker"),
            ):
                window._start_conversion([record.id])
                self.assertIn(record.id, window.file_model.checked_ids)
        finally:
            window.conversion_thread = None
            window.conversion_worker = None
            window.task_controller.finish()

    def test_terminal_conversion_clears_checked_ids_for_every_outcome(self):
        outcomes = {
            "converted": QueueProgress(total=1, completed=1, converted=1, overall_percent=100),
            "skipped": QueueProgress(total=1, completed=1, skipped=1, overall_percent=100),
            "failed": QueueProgress(total=1, completed=1, failed=1, overall_percent=100),
            "mixed": QueueProgress(total=3, completed=3, converted=1, skipped=1, failed=1, overall_percent=100),
            "canceled": QueueProgress(total=2, not_processed=2, remaining=2, canceled=True, overall_percent=0),
        }

        for name, progress in outcomes.items():
            with self.subTest(name=name):
                window = self._window()
                record = window.file_model.record_at(0)
                window.file_model.toggle_row_checked(0, True)
                window.queue_model.checked_ids.add(record.id)

                window._conversion_finished(progress)

                self.assertEqual(window.file_model.checked_ids, set())
                self.assertEqual(window.queue_model.checked_ids, set())
                self.assertEqual(window._selected_records(window.file_table, window.file_model), [])

    def test_converted_row_cannot_leave_hidden_checked_id_in_pending_filter(self):
        window = self._window()
        window.set_status_filter(FileStatus.PENDING.value)
        record = window.file_model.record_at(0)
        window.file_model.toggle_row_checked(0, True)
        window.db.update_file_status(record.id, FileStatus.CONVERTED.value)

        window._conversion_finished(
            QueueProgress(total=1, completed=1, converted=1, overall_percent=100)
        )

        self.assertNotIn(record.id, {item.id for item in window.file_model.records})
        self.assertNotIn(record.id, window.file_model.checked_ids)
        self.assertEqual(window._selected_records(window.file_table, window.file_model), [])

    def test_worker_level_failure_also_clears_checked_ids(self):
        window = self._window()
        record = window.file_model.record_at(0)
        window.file_model.toggle_row_checked(0, True)
        window.queue_model.checked_ids.add(record.id)

        with patch.object(window, "_show_dialog"):
            window._conversion_failed("worker failed")

        self.assertEqual(window.file_model.checked_ids, set())
        self.assertEqual(window.queue_model.checked_ids, set())

    def test_cancel_request_keeps_batch_until_canceled_terminal_result(self):
        window = self._window()
        record = window.file_model.record_at(0)
        window.file_model.toggle_row_checked(0, True)
        window.queue_model.checked_ids.add(record.id)
        window.conversion_worker = MagicMock()
        window.task_controller.begin_conversion()

        try:
            window.cancel_conversion()

            self.assertIn(record.id, window.file_model.checked_ids)
            self.assertIn(record.id, window.queue_model.checked_ids)
            window._conversion_finished(
                QueueProgress(total=1, not_processed=1, remaining=1, canceled=True)
            )
            self.assertEqual(window.file_model.checked_ids, set())
            self.assertEqual(window.queue_model.checked_ids, set())
        finally:
            window.conversion_worker = None
            window.task_controller.finish()

    def test_terminal_batch_reset_preserves_language_selection(self):
        window = self._window()
        record = window.file_model.record_at(0)
        window.file_model.toggle_row_checked(0, True)
        window.queue_model.checked_ids.add(record.id)
        window.file_table.selectRow(0)
        window.queue_table.selectRow(0)
        window.last_checked_row = 0
        window.last_checked_model = window.file_model
        window.context_record = record

        self.assertGreater(window.language_model.rowCount(), 0)
        language_record = window.language_model.record_at(0)
        window.language_table.selectRow(0)
        self.assertEqual(
            [item.id for item in window.language_model.selected_records(window.language_table)],
            [language_record.id],
        )

        window._conversion_finished(
            QueueProgress(total=1, completed=1, skipped=1, overall_percent=100)
        )

        self.assertEqual(window.file_model.checked_ids, set())
        self.assertEqual(window.queue_model.checked_ids, set())
        self.assertEqual(window.file_table.selectionModel().selectedRows(), [])
        self.assertEqual(window.queue_table.selectionModel().selectedRows(), [])
        self.assertIsNone(window.last_checked_row)
        self.assertIsNone(window.last_checked_model)
        self.assertIsNone(window.context_record)
        self.assertEqual(window.batch_label.text(), window._tr("batch.selected", count=0))
        self.assertIs(window.library_action_rows.currentWidget(), window.filter_bar)
        self.assertEqual(
            [item.id for item in window.language_model.selected_records(window.language_table)],
            [language_record.id],
        )

    def test_switching_library_clears_and_rejects_hidden_ids_from_old_library(self):
        window = self._window()
        old_record = window.file_model.record_at(0)
        window.file_model.toggle_row_checked(0, True)
        window.search_input.setText("no-result-filter")
        self.app.processEvents()
        self.assertNotIn(old_record.id, {item.id for item in window.file_model.records})
        self.assertIn(old_record.id, window.file_model.checked_ids)

        second = tempfile.TemporaryDirectory(prefix="ncmdump-v3-second-library-")
        self.addCleanup(second.cleanup)
        second_id = window._activate_library(second.name)

        self.assertNotEqual(second_id, old_record.library_id)
        self.assertEqual(window.file_model.checked_ids, set())
        self.assertEqual(window.queue_model.checked_ids, set())
        window.file_model.checked_ids.add(old_record.id)
        self.assertEqual(window._selected_records(window.file_table, window.file_model), [])

    def test_batch_convert_is_disabled_for_nonconvertible_only_selection(self):
        for status in (
            FileStatus.CONVERTED.value,
            FileStatus.NORMAL.value,
            FileStatus.MISSING.value,
        ):
            with self.subTest(status=status):
                window = self._window()
                record = window.file_model.record_at(0)
                window.db.update_file_status(record.id, status)
                window.refresh_files()
                row = next(index for index, item in enumerate(window.file_model.records) if item.id == record.id)
                window.file_model.toggle_row_checked(row, True)
                window._update_batch_bar()

                self.assertEqual(len(window._selected_records(window.file_table, window.file_model)), 1)
                self.assertFalse(window.batch_convert_button.isEnabled())

    def test_batch_convert_is_enabled_for_pending_or_failed_selection(self):
        for status in (FileStatus.PENDING.value, FileStatus.FAILED.value):
            with self.subTest(status=status):
                window = self._window()
                record = window.file_model.record_at(0)
                window.db.update_file_status(record.id, status)
                window.refresh_files()
                row = next(index for index, item in enumerate(window.file_model.records) if item.id == record.id)
                window.file_model.toggle_row_checked(row, True)
                window._update_batch_bar()

                self.assertTrue(window.batch_convert_button.isEnabled())

    def test_library_search_stays_visible_and_checked_ids_survive_filtering(self):
        window = self._window()
        selected = window.file_model.record_at(0)
        search_target = window.file_model.record_at(window.file_model.rowCount() - 1)
        self.assertNotEqual(selected.id, search_target.id)

        window.file_model.toggle_row_checked(0, True)
        window.search_input.setFocus()
        window.search_input.setText(Path(search_target.relative_path).name)
        self.app.processEvents()

        visible_ids = {record.id for record in window.file_model.records}
        self.assertNotIn(selected.id, visible_ids)
        self.assertIn(selected.id, window.file_model.checked_ids)
        self.assertTrue(window.search_input.isVisibleTo(window))
        self.assertIs(window.library_action_rows.currentWidget(), window.batch_bar)
        self.assertEqual(
            [record.id for record in window._selected_records(window.file_table, window.file_model)],
            [selected.id],
        )

        window.search_input.clear()
        self.app.processEvents()
        self.assertIn(selected.id, window.file_model.checked_ids)
        self.assertTrue(window.search_input.hasFocus())

    def test_library_action_rows_share_dimensions_and_search_uses_free_width(self):
        window = self._window()
        filter_buttons = list(window.status_chips.values())
        batch_buttons = [
            window.batch_convert_button,
            window.batch_retry_button,
            window.batch_ignore_button,
            window.batch_copy_button,
            window.batch_reveal_button,
            window.batch_clear_button,
        ]

        self.assertEqual(window.library_action_slot.height(), LIBRARY_ACTION_SLOT_HEIGHT)
        self.assertEqual(window.search_input.height(), LIBRARY_ACTION_CONTROL_HEIGHT)
        self.assertEqual(window.filter_bar.height(), LIBRARY_ACTION_CONTROL_HEIGHT)
        self.assertEqual(window.batch_bar.height(), LIBRARY_ACTION_CONTROL_HEIGHT)
        self.assertEqual(window.library_action_rows.height(), LIBRARY_ACTION_CONTROL_HEIGHT)
        for button in [*filter_buttons, *batch_buttons]:
            self.assertEqual(button.height(), LIBRARY_ACTION_CONTROL_HEIGHT)
            self.assertTrue(button.property("libraryAction"))

        window.search_input.setText("Track")
        self.app.processEvents()
        self.assertTrue(window.reset_filters_button.isVisibleTo(window))
        for control in (window.search_input, window.format_filter, window.reset_filters_button):
            self.assertEqual(control.height(), LIBRARY_ACTION_CONTROL_HEIGHT)
            self.assertTrue(control.property("libraryAction"))
        search_bottom = (
            window.search_input.mapTo(window.library_action_slot, QPoint(0, 0)).y()
            + window.search_input.height()
        )
        action_top = window.library_action_rows.mapTo(window.library_action_slot, QPoint(0, 0)).y()
        self.assertEqual(action_top - search_bottom, LIBRARY_ACTION_ROW_GAP)

        style = window.styleSheet()
        self.assertIn('QPushButton[libraryAction="true"]', style)
        self.assertIn(f"border-radius: {LIBRARY_ACTION_RADIUS}px", style)

        window.result_count_label.setText("Showing 12,345 pending tracks")
        self.app.processEvents()
        width_at_960 = window.search_input.width()
        self.assertGreaterEqual(width_at_960, 220)

        window.resize(1280, 800)
        self.app.processEvents()
        self.assertGreaterEqual(window.search_input.width(), width_at_960 + 240)

    def test_empty_library_never_enables_convert_all(self):
        window = self._window(populated=False)
        window._update_queue_actions()
        self.assertFalse(window.start_button.isEnabled())
        self.assertEqual(window.file_model.checked_records(), [])

    def test_output_location_action_opens_the_output_parent_directory(self):
        window = self._window()
        record = window.file_model.record_at(0)
        output_dir = Path(tempfile.mkdtemp(prefix="ncmdump output, "))
        self.addCleanup(lambda: output_dir.rmdir())
        output = output_dir / "Artist - Song.flac"
        output.write_bytes(b"fLaC")
        self.addCleanup(output.unlink)
        record.output_path = str(output)

        with patch.object(window, "_open_folder") as open_folder:
            window._reveal_output_record(record)

        open_folder.assert_called_once_with(output_dir)

    def test_core_controls_are_accessible_single_line_and_contained(self):
        window = self._window()
        self.assertTrue(window.sidebar.accessibleName())
        self.assertTrue(window.library_path_label.accessibleName())
        self.assertTrue(window.start_button.accessibleName())
        self.assertTrue(window.progress_panel.accessibleName())
        self.assertFalse(window.library_path_label.wordWrap())
        self.assertFalse(window.progress_panel.detail_label.wordWrap())
        self.assertFalse(window.progress_panel.metrics_label.wordWrap())
        self.assertIs(window.library_action_slot.parentWidget(), window.library_data_panel)
        self.assertIs(window.table_stack.parentWidget(), window.library_data_panel)
        self.assertEqual(window.library_data_panel.layout().spacing(), 0)
        self.assertTrue(window.file_table.property("embeddedLibrary"))

        for widget in (
            window.findChild(type(window.library_action_slot), "libraryActionSlot"),
            window.progress_panel,
            window.pages,
        ):
            origin = widget.mapTo(window, QPoint(0, 0))
            self.assertGreaterEqual(origin.x(), 0)
            self.assertGreaterEqual(origin.y(), 0)
            self.assertLessEqual(origin.x() + widget.width(), window.width())
            self.assertLessEqual(origin.y() + widget.height(), window.height())


if __name__ == "__main__":
    unittest.main()
