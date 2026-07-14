from __future__ import annotations

import sqlite3
import subprocess
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from ncmdump.conversion_queue import ConversionQueue
from ncmdump.core import NCMConversionCanceled, NCMTaggingError, dump
from ncmdump.library_db import LibraryDB
from ncmdump.library_scanner import scan_library
from ncmdump.models import AppSettings, FileStatus, QueueProgress, TaskState
from ncmdump.platform_integration import (
    FileManagerStatus,
    _windows_reveal_command,
    open_folder,
    reveal_in_file_manager,
)


class V3DataReliabilityTests(unittest.TestCase):
    def test_v1_database_migrates_in_place_with_source_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "legacy.sqlite3"
            with closing(sqlite3.connect(db_path)) as connection:
                connection.executescript(
                    """
                    CREATE TABLE libraries (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        path TEXT NOT NULL UNIQUE,
                        selected INTEGER NOT NULL DEFAULT 0,
                        last_scan_at TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE files (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        library_id INTEGER NOT NULL,
                        relative_path TEXT NOT NULL,
                        absolute_path TEXT NOT NULL,
                        file_size INTEGER NOT NULL DEFAULT 0,
                        modified_time INTEGER NOT NULL DEFAULT 0,
                        fingerprint TEXT NOT NULL DEFAULT '',
                        strict_hash TEXT,
                        extension TEXT NOT NULL DEFAULT '',
                        status TEXT NOT NULL DEFAULT 'unknown',
                        output_path TEXT,
                        failure_reason TEXT,
                        last_scan_at TEXT,
                        last_seen_at TEXT,
                        ignored INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        UNIQUE(library_id, relative_path)
                    );
                    INSERT INTO libraries(path, selected, created_at, updated_at)
                    VALUES('C:/Music', 1, 'before', 'before');
                    INSERT INTO files(
                        library_id, relative_path, absolute_path, file_size,
                        modified_time, fingerprint, extension, status,
                        created_at, updated_at
                    ) VALUES(1, 'old.ncm', 'C:/Music/old.ncm', 10, 1,
                             'legacy', '.ncm', 'pending', 'before', 'before');
                    PRAGMA user_version=1;
                    """
                )
                connection.commit()

            db = LibraryDB(str(db_path))
            migrated = db.get_file(1)
            self.assertIsNotNone(migrated)
            self.assertEqual(migrated.relative_path, "old.ncm")
            self.assertFalse(migrated.source_deleted)
            with closing(sqlite3.connect(db_path)) as connection:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                columns = {
                    row[1] for row in connection.execute("PRAGMA table_info(files)")
                }
            self.assertGreaterEqual(version, 2)
            self.assertIn("source_deleted", columns)

    def test_full_scan_cancel_preserves_existing_ids_and_ignore_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "music"
            root.mkdir()
            (root / "first.ncm").write_bytes(b"first")
            (root / "second.ncm").write_bytes(b"second")
            db = LibraryDB(str(Path(tmp) / "state.sqlite3"))
            settings = AppSettings(music_library_path=str(root))
            scan_library(db, str(root), settings)
            library_id = db.get_selected_library()["id"]
            before = db.files_by_relative_path(library_id)
            db.mark_ignored([before["second.ncm"].id], True)
            before = db.files_by_relative_path(library_id)

            canceled = threading.Event()
            canceled.set()
            result = scan_library(
                db,
                str(root),
                settings,
                cancel_event=canceled,
                scan_mode="full",
            )

            self.assertTrue(result.canceled)
            after = db.files_by_relative_path(library_id)
            self.assertEqual(set(after), set(before))
            self.assertEqual(
                {name: record.id for name, record in after.items()},
                {name: record.id for name, record in before.items()},
            )
            self.assertTrue(after["second.ncm"].ignored)
            self.assertEqual(after["second.ncm"].status, FileStatus.IGNORED.value)

    def test_successful_full_scan_preserves_matched_id_and_removes_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "music"
            root.mkdir()
            keep = root / "keep.ncm"
            stale = root / "stale.ncm"
            keep.write_bytes(b"keep")
            stale.write_bytes(b"stale")
            db = LibraryDB(str(Path(tmp) / "state.sqlite3"))
            settings = AppSettings(music_library_path=str(root))
            scan_library(db, str(root), settings)
            library_id = db.get_selected_library()["id"]
            before = db.files_by_relative_path(library_id)
            keep_id = before["keep.ncm"].id
            stale.unlink()

            result = scan_library(db, str(root), settings, scan_mode="full")

            self.assertFalse(result.canceled)
            after = db.files_by_relative_path(library_id)
            self.assertEqual(set(after), {"keep.ncm"})
            self.assertEqual(after["keep.ncm"].id, keep_id)

    def test_unignore_reclassifies_ncm_and_normal_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "music"
            root.mkdir()
            (root / "pending.ncm").write_bytes(b"pending")
            (root / "normal.mp3").write_bytes(b"normal")
            db = LibraryDB(str(Path(tmp) / "state.sqlite3"))
            settings = AppSettings(music_library_path=str(root))
            scan_library(db, str(root), settings)
            library_id = db.get_selected_library()["id"]
            records = db.files_by_relative_path(library_id)
            ids = [records["pending.ncm"].id, records["normal.mp3"].id]
            db.mark_ignored(ids, True)
            db.mark_ignored(ids, False)
            records = db.files_by_relative_path(library_id)
            self.assertEqual(records["pending.ncm"].status, FileStatus.PENDING.value)
            self.assertEqual(records["normal.mp3"].status, FileStatus.NORMAL.value)

    def test_queue_progress_keeps_success_compatibility_alias(self):
        progress = QueueProgress(converted=2, state=TaskState.CONVERTING.value)
        self.assertEqual(progress.success, 2)
        progress.success = 3
        self.assertEqual(progress.converted, 3)


class V3ConversionReliabilityTests(unittest.TestCase):
    def _pending_record(self, tmp: str):
        root = Path(tmp) / "music"
        root.mkdir()
        source = root / "track.ncm"
        source.write_bytes(b"source")
        db = LibraryDB(str(Path(tmp) / "state.sqlite3"))
        settings = AppSettings(music_library_path=str(root), max_concurrent_conversions=1)
        scan_library(db, str(root), settings)
        library = db.get_selected_library()
        record = db.files_by_relative_path(library["id"])["track.ncm"]
        return db, settings, library["id"], record

    def test_core_tag_failure_keeps_existing_output_and_removes_temp_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "track.ncm"
            source.write_bytes(b"encrypted audio")
            output = source.with_suffix(".flac")
            original = b"fLaC" + b"old output"
            output.write_bytes(original)

            with (
                patch(
                    "ncmdump.core.read_ncm_file",
                    return_value=(b"\0" * 16384, {"format": "flac"}, None, ""),
                ),
                patch(
                    "ncmdump.core._write_media_tags",
                    side_effect=NCMTaggingError("tag failure"),
                ),
            ):
                with self.assertRaises(NCMTaggingError):
                    dump(source, output_path=output, skip=False)

            self.assertEqual(output.read_bytes(), original)
            self.assertEqual(list(Path(tmp).glob(".track.ncmdump-*.flac")), [])

    def test_core_mid_write_cancel_removes_temp_and_final_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "track.ncm"
            source.write_bytes(b"x" * (16384 * 3))
            output = source.with_suffix(".flac")
            canceled = False

            def progress_callback(written, total, path):
                nonlocal canceled
                canceled = written > 0

            with patch(
                "ncmdump.core.read_ncm_file",
                return_value=(b"\0" * 16384, {"format": "flac"}, None, ""),
            ):
                with self.assertRaises(NCMConversionCanceled):
                    dump(
                        source,
                        output_path=output,
                        skip=False,
                        progress_callback=progress_callback,
                        cancel_callback=lambda: canceled,
                    )

            self.assertFalse(output.exists())
            self.assertEqual(list(Path(tmp).glob(".track.ncmdump-*.flac")), [])

    def test_type_error_inside_dump_is_not_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, settings, library_id, record = self._pending_record(tmp)
            calls = 0

            def broken_dump(input_path, **kwargs):
                nonlocal calls
                calls += 1
                raise TypeError("internal conversion bug")

            progress = ConversionQueue(db, dump_func=broken_dump).run_records(
                library_id,
                settings.music_library_path,
                settings,
                [record],
            )
            self.assertEqual(calls, 1)
            self.assertEqual(progress.failed, 1)
            self.assertEqual(progress.converted, 0)

    def test_cancellation_keeps_pending_state_history_clean_and_removes_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, settings, library_id, record = self._pending_record(tmp)
            output = Path(record.absolute_path).with_suffix(".flac")

            def canceled_dump(input_path, output_path=None, **kwargs):
                target = Path(output_path(input_path, {"format": "flac"}))
                target.write_bytes(b"partial")
                raise NCMConversionCanceled("cancel")

            progress = ConversionQueue(db, dump_func=canceled_dump).run_records(
                library_id,
                settings.music_library_path,
                settings,
                [record],
            )

            refreshed = db.get_file(record.id)
            self.assertTrue(progress.canceled)
            self.assertEqual(progress.failed, 0)
            self.assertEqual(progress.not_processed, 1)
            self.assertEqual(refreshed.status, FileStatus.PENDING.value)
            self.assertEqual(db.list_history(library_id), [])
            self.assertFalse(output.exists())

    def test_valid_existing_output_is_counted_as_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, settings, library_id, record = self._pending_record(tmp)
            output = Path(record.absolute_path).with_suffix(".flac")
            output.write_bytes(b"fLaC" + b"\x00" * 64)

            def skip_dump(input_path, output_path=None, **kwargs):
                return output_path(input_path, {"format": "flac"})

            progress = ConversionQueue(db, dump_func=skip_dump).run_records(
                library_id,
                settings.music_library_path,
                settings,
                [record],
            )

            refreshed = db.get_file(record.id)
            self.assertEqual(progress.skipped, 1)
            self.assertEqual(progress.converted, 0)
            self.assertEqual(progress.failed, 0)
            self.assertEqual(refreshed.status, FileStatus.CONVERTED.value)
            self.assertEqual(db.list_history(library_id)[0]["status"], "skipped")

    def test_nonempty_invalid_audio_output_is_failed_not_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, settings, library_id, record = self._pending_record(tmp)
            output = Path(record.absolute_path).with_suffix(".flac")
            output.write_bytes(b"not really an audio file")

            def invalid_dump(input_path, output_path=None, **kwargs):
                return output_path(input_path, {"format": "flac"})

            progress = ConversionQueue(db, dump_func=invalid_dump).run_records(
                library_id,
                settings.music_library_path,
                settings,
                [record],
            )

            refreshed = db.get_file(record.id)
            self.assertEqual(progress.skipped, 0)
            self.assertEqual(progress.converted, 0)
            self.assertEqual(progress.failed, 1)
            self.assertEqual(refreshed.status, FileStatus.FAILED.value)
            self.assertEqual(db.list_history(library_id)[0]["status"], "failed")

    def test_progress_sequences_are_monotonic_and_throttled(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, settings, library_id, record = self._pending_record(tmp)
            events = []

            def noisy_dump(input_path, output_path=None, progress_callback=None, **kwargs):
                target = Path(output_path(input_path, {"format": "flac"}))
                for value in range(1, 1001):
                    progress_callback(value, 1000, str(target))
                target.write_bytes(b"fLaC" + b"\x00" * 64)
                return str(target)

            progress = ConversionQueue(db, dump_func=noisy_dump).run_records(
                library_id,
                settings.music_library_path,
                settings,
                [record],
                events.append,
            )

            sequences = [event.sequence for event in events]
            percentages = [event.overall_percent for event in events]
            self.assertEqual(sequences, sorted(set(sequences)))
            self.assertEqual(percentages, sorted(percentages))
            self.assertLess(len(events), 20)
            self.assertEqual(progress.overall_percent, 100.0)


class V3PlatformIntegrationTests(unittest.TestCase):
    def test_windows_reveal_keeps_unicode_spaces_and_commas_as_a_path_argument(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "中文 音乐,现场.ncm"
            target.write_bytes(b"ncm")
            calls = []

            with (
                patch("ncmdump.platform_integration.sys.platform", "win32"),
                patch("ncmdump.platform_integration._spawn", calls.append),
            ):
                result = reveal_in_file_manager(target)

            self.assertEqual(result.status, FileManagerStatus.REVEALED)
            self.assertEqual(
                calls,
                [["explorer.exe", "/select,", str(target.absolute())]],
            )
            command_line = subprocess.list2cmdline(calls[0])
            self.assertIn("explorer.exe /select,", command_line)
            self.assertNotIn('"/select,', command_line)

    def test_windows_unc_reveal_command_preserves_path_verbatim(self):
        unc_path = r"\\server\共享 音乐\现场,录音.ncm"
        self.assertEqual(
            _windows_reveal_command(unc_path),
            ["explorer.exe", "/select,", unc_path],
        )

    def test_windows_open_folder_uses_the_real_parent_for_a_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "Music Library, Live"
            folder.mkdir()
            output = folder / "Artist - Song.flac"
            output.write_bytes(b"fLaC")
            calls = []

            with (
                patch("ncmdump.platform_integration.sys.platform", "win32"),
                patch("ncmdump.platform_integration._spawn", calls.append),
            ):
                result = open_folder(output)

            self.assertEqual(result.status, FileManagerStatus.OPENED)
            self.assertEqual(result.opened_path, str(folder.absolute()))
            self.assertEqual(calls, [["explorer.exe", str(folder.absolute())]])

    def test_missing_reveal_target_is_reported_without_launching(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.ncm"
            with patch("ncmdump.platform_integration._spawn") as spawn:
                result = reveal_in_file_manager(missing)

            self.assertEqual(result.status, FileManagerStatus.NOT_FOUND)
            self.assertFalse(result.ok)
            spawn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
