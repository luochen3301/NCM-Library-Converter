from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from ncmdump.conversion_queue import ConversionQueue
from ncmdump.library_db import LibraryDB
from ncmdump.library_scanner import scan_library
from ncmdump.models import AppSettings, FileStatus, TaskState


class MutablePath:
    """PathLike used to prove a queue freezes its library path at startup."""

    def __init__(self, value: Path):
        self.value = value
        self.calls = 0

    def __fspath__(self) -> str:
        self.calls += 1
        return str(self.value)


class V3TaskLifecycleTests(unittest.TestCase):
    def _make_pending_record(
        self,
        tmp: str,
        relative_path: str = "track.ncm",
        *,
        settings: AppSettings | None = None,
    ):
        root = Path(tmp) / "music"
        source = root / relative_path
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"ncm source")
        db = LibraryDB(str(Path(tmp) / "state.sqlite3"))
        settings = settings or AppSettings(
            music_library_path=str(root),
            max_concurrent_conversions=1,
        )
        settings.music_library_path = str(root)
        scan_library(db, str(root), settings)
        library_id = int(db.get_selected_library()["id"])
        record = db.get_file_by_relative(library_id, Path(relative_path).as_posix())
        self.assertIsNotNone(record)
        return root, source, db, settings, library_id, record

    @staticmethod
    def _record_state(record):
        return (
            record.id,
            record.relative_path,
            record.absolute_path,
            record.file_size,
            record.modified_time,
            record.fingerprint,
            record.strict_hash,
            record.extension,
            record.status,
            record.output_path,
            record.failure_reason,
            record.ignored,
            record.source_deleted,
        )

    def test_scan_traversal_exception_does_not_modify_existing_index_or_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "music"
            root.mkdir()
            (root / "keep.ncm").write_bytes(b"keep")
            (root / "ignored.ncm").write_bytes(b"ignored")
            db = LibraryDB(str(Path(tmp) / "state.sqlite3"))
            settings = AppSettings(music_library_path=str(root))
            scan_library(db, str(root), settings)
            library_id = int(db.get_selected_library()["id"])
            ignored = db.get_file_by_relative(library_id, "ignored.ncm")
            keep = db.get_file_by_relative(library_id, "keep.ncm")
            db.mark_ignored([ignored.id], True)
            db.add_history(
                keep.id,
                library_id,
                keep.absolute_path,
                str(root / "keep.flac"),
                keep.fingerprint,
                "success",
            )
            before = {
                path: self._record_state(record)
                for path, record in db.files_by_relative_path(library_id).items()
            }
            history_before = [dict(row) for row in db.list_history(library_id)]
            last_scan_before = db.get_library(library_id)["last_scan_at"]
            (root / "new.ncm").write_bytes(b"new")

            with patch(
                "ncmdump.library_scanner.compute_fingerprint",
                side_effect=RuntimeError("simulated traversal failure"),
            ):
                with self.assertRaisesRegex(RuntimeError, "traversal failure"):
                    scan_library(db, str(root), settings, scan_mode="full")

            after = {
                path: self._record_state(record)
                for path, record in db.files_by_relative_path(library_id).items()
            }
            self.assertEqual(after, before)
            self.assertEqual([dict(row) for row in db.list_history(library_id)], history_before)
            self.assertEqual(db.get_library(library_id)["last_scan_at"], last_scan_before)

    def test_scan_commit_exception_rolls_back_partially_upserted_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "music"
            root.mkdir()
            (root / "existing.ncm").write_bytes(b"existing")
            db = LibraryDB(str(Path(tmp) / "state.sqlite3"))
            settings = AppSettings(music_library_path=str(root))
            scan_library(db, str(root), settings)
            library_id = int(db.get_selected_library()["id"])
            before = {
                path: self._record_state(record)
                for path, record in db.files_by_relative_path(library_id).items()
            }
            (root / "new-a.ncm").write_bytes(b"a")
            (root / "new-b.ncm").write_bytes(b"b")
            original_upsert = db._upsert_file_on_connection
            calls = 0

            def fail_after_one_upsert(connection, record, now):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise RuntimeError("simulated commit failure")
                return original_upsert(connection, record, now)

            with patch.object(
                db,
                "_upsert_file_on_connection",
                side_effect=fail_after_one_upsert,
            ):
                with self.assertRaisesRegex(RuntimeError, "commit failure"):
                    scan_library(db, str(root), settings, scan_mode="full")

            after = {
                path: self._record_state(record)
                for path, record in db.files_by_relative_path(library_id).items()
            }
            self.assertGreaterEqual(calls, 2)
            self.assertEqual(after, before)

    def test_cancel_before_retry_start_keeps_failed_status_and_history_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _source, db, settings, library_id, record = self._make_pending_record(tmp)
            db.update_file_status(
                record.id,
                FileStatus.FAILED.value,
                failure_reason="previous failure",
            )
            calls = 0

            def dump_must_not_run(*args, **kwargs):
                nonlocal calls
                calls += 1
                raise AssertionError("pre-canceled retry unexpectedly started")

            queue = ConversionQueue(db, dump_func=dump_must_not_run)
            queue.cancel()
            progress = queue.run_file_ids(
                library_id,
                str(root),
                settings,
                [record.id],
            )

            refreshed = db.get_file(record.id)
            self.assertEqual(calls, 0)
            self.assertTrue(progress.canceled)
            self.assertEqual(progress.not_processed, 1)
            self.assertEqual(progress.completed, 0)
            self.assertEqual(progress.state, TaskState.IDLE)
            self.assertEqual(refreshed.status, FileStatus.FAILED.value)
            self.assertEqual(refreshed.failure_reason, "previous failure")
            self.assertEqual(db.list_history(library_id), [])

    def test_active_conversion_honors_pause_then_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _source, db, settings, library_id, record = self._make_pending_record(tmp)
            entered_dump = threading.Event()
            inspect_pause = threading.Event()
            pause_observed = threading.Event()
            resumed = threading.Event()
            result = []
            errors = []

            def cooperative_dump(
                input_path,
                output_path=None,
                pause_callback=None,
                **kwargs,
            ):
                entered_dump.set()
                if not inspect_pause.wait(3):
                    raise RuntimeError("test did not request pause inspection")
                if pause_callback and pause_callback():
                    pause_observed.set()
                deadline = time.monotonic() + 3
                while pause_callback and pause_callback():
                    if time.monotonic() >= deadline:
                        raise RuntimeError("conversion was never resumed")
                    time.sleep(0.01)
                resumed.set()
                target = Path(output_path(input_path, {"format": "flac"}))
                target.write_bytes(b"fLaC" + b"\0" * 32)
                return str(target)

            queue = ConversionQueue(db, dump_func=cooperative_dump)

            def run_queue():
                try:
                    result.append(
                        queue.run_records(
                            library_id,
                            str(root),
                            settings,
                            [record],
                        )
                    )
                except BaseException as exc:  # surfaced on the test thread below
                    errors.append(exc)

            worker = threading.Thread(target=run_queue, daemon=True)
            worker.start()
            self.assertTrue(entered_dump.wait(3), "conversion did not start")
            queue.pause()
            inspect_pause.set()
            self.assertTrue(pause_observed.wait(3), "dump did not observe pause")
            self.assertEqual(queue.progress.state, TaskState.PAUSED)
            self.assertTrue(queue.progress.paused)
            self.assertFalse(resumed.is_set())

            queue.resume()
            worker.join(5)
            self.assertFalse(worker.is_alive(), "conversion did not finish after resume")
            self.assertEqual(errors, [])
            self.assertTrue(resumed.is_set())
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0].converted, 1)
            self.assertFalse(result[0].paused)
            self.assertEqual(result[0].state, TaskState.IDLE)

    def test_conversion_freezes_settings_and_library_path_at_task_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "music-a"
            source = root / "album" / "track.ncm"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"ncm source")
            output_a = Path(tmp) / "output-a"
            output_b = Path(tmp) / "output-b"
            settings = AppSettings(
                music_library_path=str(root),
                output_location="custom_folder",
                custom_output_folder=str(output_a),
                preserve_folder_structure=True,
                delete_source_after_success=False,
                skip_existing_output=True,
                max_concurrent_conversions=1,
            )
            db = LibraryDB(str(Path(tmp) / "state.sqlite3"))
            scan_library(db, str(root), settings)
            library_id = int(db.get_selected_library()["id"])
            record = db.get_file_by_relative(library_id, "album/track.ncm")
            path_snapshot_probe = MutablePath(root)
            entered_dump = threading.Event()
            continue_dump = threading.Event()
            captured = {}
            result = []
            errors = []

            def blocking_dump(input_path, output_path=None, skip=None, **kwargs):
                captured["skip"] = skip
                entered_dump.set()
                if not continue_dump.wait(3):
                    raise RuntimeError("test did not release conversion")
                target = Path(output_path(input_path, {"format": "flac"}))
                captured["target"] = target
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"fLaC" + b"\0" * 32)
                return str(target)

            queue = ConversionQueue(db, dump_func=blocking_dump)

            def run_queue():
                try:
                    result.append(
                        queue.run_records(
                            library_id,
                            path_snapshot_probe,
                            settings,
                            [record],
                        )
                    )
                except BaseException as exc:
                    errors.append(exc)

            worker = threading.Thread(target=run_queue, daemon=True)
            worker.start()
            self.assertTrue(entered_dump.wait(3), "conversion did not start")

            settings.custom_output_folder = str(output_b)
            settings.preserve_folder_structure = False
            settings.delete_source_after_success = True
            settings.skip_existing_output = False
            path_snapshot_probe.value = Path(tmp) / "music-b"
            continue_dump.set()

            worker.join(5)
            self.assertFalse(worker.is_alive(), "conversion did not finish")
            self.assertEqual(errors, [])
            self.assertEqual(len(result), 1)
            expected = output_a / "album" / "track.flac"
            self.assertEqual(captured["target"], expected)
            self.assertEqual(captured["skip"], True)
            self.assertEqual(path_snapshot_probe.calls, 1)
            self.assertTrue(expected.is_file())
            self.assertFalse((output_b / "track.flac").exists())
            self.assertTrue(source.exists(), "mutated delete setting leaked into running task")

    def test_successful_delete_marks_source_and_full_scan_retains_history_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = AppSettings(
                delete_source_after_success=True,
                max_concurrent_conversions=1,
            )
            root, source, db, settings, library_id, record = self._make_pending_record(
                tmp,
                settings=settings,
            )

            def successful_dump(input_path, output_path=None, **kwargs):
                target = Path(output_path(input_path, {"format": "flac"}))
                target.write_bytes(b"fLaC" + b"\0" * 32)
                return str(target)

            progress = ConversionQueue(db, dump_func=successful_dump).run_records(
                library_id,
                str(root),
                settings,
                [record],
            )
            converted = db.get_file(record.id)
            history = db.list_history(library_id)

            self.assertEqual(progress.converted, 1)
            self.assertFalse(source.exists())
            self.assertTrue(Path(converted.output_path).is_file())
            self.assertEqual(converted.status, FileStatus.CONVERTED.value)
            self.assertTrue(converted.source_deleted)
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["status"], "success")
            self.assertEqual(history[0]["file_id"], record.id)

            scan_library(db, str(root), settings, scan_mode="full")
            retained = db.get_file(record.id)
            history_after = db.list_history(library_id)
            self.assertIsNotNone(retained)
            self.assertEqual(retained.relative_path, "track.ncm")
            self.assertEqual(retained.status, FileStatus.CONVERTED.value)
            self.assertTrue(retained.source_deleted)
            self.assertEqual(history_after[0]["file_id"], record.id)

    def test_persistence_failure_never_deletes_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = AppSettings(
                delete_source_after_success=True,
                max_concurrent_conversions=1,
            )
            root, source, db, settings, library_id, record = self._make_pending_record(
                tmp,
                settings=settings,
            )

            def successful_dump(input_path, output_path=None, **kwargs):
                target = Path(output_path(input_path, {"format": "flac"}))
                target.write_bytes(b"fLaC" + b"\0" * 32)
                return str(target)

            with patch.object(
                db,
                "record_conversion_result",
                side_effect=RuntimeError("database unavailable"),
            ):
                progress = ConversionQueue(db, dump_func=successful_dump).run_records(
                    library_id,
                    str(root),
                    settings,
                    [record],
                )

            refreshed = db.get_file(record.id)
            self.assertEqual(progress.failed, 1)
            self.assertTrue(source.exists())
            self.assertEqual(refreshed.status, FileStatus.PENDING.value)
            self.assertFalse(refreshed.source_deleted)
            self.assertEqual(db.list_history(library_id), [])

    def test_delete_failure_clears_source_deleted_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = AppSettings(
                delete_source_after_success=True,
                max_concurrent_conversions=1,
            )
            root, source, db, settings, library_id, record = self._make_pending_record(
                tmp,
                settings=settings,
            )

            def successful_dump(input_path, output_path=None, **kwargs):
                target = Path(output_path(input_path, {"format": "flac"}))
                target.write_bytes(b"fLaC" + b"\0" * 32)
                return str(target)

            with patch(
                "ncmdump.conversion_queue.os.remove",
                side_effect=PermissionError("source is locked"),
            ):
                progress = ConversionQueue(db, dump_func=successful_dump).run_records(
                    library_id,
                    str(root),
                    settings,
                    [record],
                )

            refreshed = db.get_file(record.id)
            self.assertEqual(progress.converted, 1)
            self.assertTrue(source.exists())
            self.assertEqual(refreshed.status, FileStatus.CONVERTED.value)
            self.assertFalse(refreshed.source_deleted)
            self.assertEqual(db.list_history(library_id)[0]["status"], "success")


if __name__ == "__main__":
    unittest.main()
