import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from ncmdump.conversion_queue import ConversionQueue
from ncmdump.i18n import TRANSLATIONS, Translator
from ncmdump.language_classifier import classify_track_text
from ncmdump.library_db import LibraryDB
from ncmdump.library_scanner import scan_library
from ncmdump.models import AppSettings, FileRecord, FileStatus


def make_ui_record(file_id: int, relative_path: str, status: str = FileStatus.PENDING.value) -> FileRecord:
    return FileRecord(
        id=file_id,
        library_id=1,
        relative_path=relative_path,
        absolute_path=str(Path("C:/music") / relative_path),
        file_size=1024,
        modified_time=0,
        fingerprint=f"fingerprint-{file_id}",
        strict_hash=None,
        extension=Path(relative_path).suffix,
        status=status,
    )


class LibraryServiceTests(unittest.TestCase):
    def make_db(self, tmp: tempfile.TemporaryDirectory) -> LibraryDB:
        return LibraryDB(str(Path(tmp.name) / "state.sqlite3"))

    def test_settings_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = LibraryDB(str(Path(tmp) / "state.sqlite3"))
            settings = AppSettings(music_library_path=str(Path(tmp) / "music"), max_concurrent_conversions=3)
            db.save_settings(settings)
            loaded = db.get_settings()
            self.assertEqual(loaded.music_library_path, settings.music_library_path)
            self.assertEqual(loaded.max_concurrent_conversions, 3)

    def test_invalid_concurrency_setting_falls_back_to_default(self):
        settings = AppSettings.from_mapping({"max_concurrent_conversions": "many"})
        self.assertEqual(settings.max_concurrent_conversions, 2)

    def test_startup_behavior_round_trip_and_legacy_auto_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = LibraryDB(str(Path(tmp) / "state.sqlite3"))
            settings = AppSettings(music_library_path=str(Path(tmp) / "music"), startup_behavior="cache_only")
            db.save_settings(settings)
            loaded = db.get_settings()
            self.assertEqual(loaded.startup_behavior, "cache_only")
            self.assertFalse(loaded.auto_scan_on_startup)

            legacy = {"music_library_path": str(Path(tmp) / "music"), "auto_scan_on_startup": False}
            with db._connect() as connection:
                connection.execute(
                    "UPDATE settings SET value=? WHERE key='app_settings'",
                    (json.dumps(legacy),),
                )
            loaded = db.get_settings()
            self.assertEqual(loaded.startup_behavior, "cache_only")

    def test_language_setting_round_trip_and_invalid_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = LibraryDB(str(Path(tmp) / "state.sqlite3"))
            settings = AppSettings(music_library_path=str(Path(tmp) / "music"), language="zh_CN")
            db.save_settings(settings)
            loaded = db.get_settings()
            self.assertEqual(loaded.language, "zh_CN")

            invalid = {"music_library_path": str(Path(tmp) / "music"), "language": "de"}
            with db._connect() as connection:
                connection.execute(
                    "UPDATE settings SET value=? WHERE key='app_settings'",
                    (json.dumps(invalid),),
                )
            loaded = db.get_settings()
            self.assertEqual(loaded.language, "system")

    def test_theme_setting_maps_legacy_dark_values_to_v3_dark(self):
        self.assertEqual(AppSettings.from_mapping({}).theme, "dark")
        self.assertEqual(AppSettings.from_mapping({"theme": "obsidian"}).theme, "dark")
        self.assertEqual(AppSettings.from_mapping({"theme": "dark"}).theme, "dark")
        self.assertEqual(AppSettings.from_mapping({"theme": "light"}).theme, "light")
        self.assertEqual(AppSettings.from_mapping({"theme": "neon"}).theme, "dark")

    def test_language_classifier_detects_common_filename_scripts(self):
        cases = {
            "周杰伦 - 稻香.ncm": "zh",
            "Taylor Swift - August.flac": "en",
            "宇多田ヒカル - First Love.mp3": "ja",
            "아이유 - 좋은 날.ncm": "ko",
            "周杰伦 Taylor duet.ncm": "mixed",
            "Баста - Сансара.mp3": "other",
            "01 - 02.ncm": "unknown",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(classify_track_text(text).language, expected)

    def test_translation_catalogs_match_and_format_new_ui_strings(self):
        self.assertEqual(set(TRANSLATIONS["en"]), set(TRANSLATIONS["zh_CN"]))
        self.assertEqual(Translator("en").t("empty.history.title"), "No history yet")
        self.assertIn("2", Translator("zh_CN").t("queue.summary", pending=2, failed=1))

    def test_file_table_checked_ids_survive_visible_record_changes(self):
        from ncmdump.ui.qml_models import LibraryTableModel

        first = make_ui_record(1, "first.ncm")
        second = make_ui_record(2, "second.ncm")
        model = LibraryTableModel()
        model.set_records([first, second])

        model.toggleChecked(0)
        self.assertEqual(model.checked_ids, {1})

        model.set_records([second])
        self.assertEqual(model.records_for_ids(model.checked_ids), [])

        model.set_records([first])
        self.assertEqual([record.id for record in model.records_for_ids(model.checked_ids)], [1])

    def test_file_table_toggle_row_checked_can_uncheck_same_row(self):
        from ncmdump.ui.qml_models import LibraryTableModel

        model = LibraryTableModel()
        model.set_records([make_ui_record(1, "first.ncm")])

        model.toggleChecked(0)
        self.assertEqual(model.checked_ids, {1})

        model.toggleChecked(0)
        self.assertEqual(model.checked_ids, set())

    def test_failure_group_key_classifies_common_errors(self):
        from ncmdump.ui.bridge import _failure_group_key

        cases = {
            "No permission to read the source or write the output file.": "permission",
            "The output folder is unavailable.": "output",
            "File does not exist or was moved.": "missing",
            "Not enough disk space for the output file.": "disk",
            "The file is currently in use by another application.": "busy",
            "The file path is too long for this system.": "path",
            "NCM metadata parsing failed.": "format",
            "Unexpected conversion failure.": "other",
        }
        for message, expected in cases.items():
            with self.subTest(message=message):
                self.assertEqual(_failure_group_key(message), expected)

    def test_scan_statuses_ignore_and_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "music"
            root.mkdir()
            (root / "converted.ncm").write_bytes(b"source")
            (root / "converted.flac").write_bytes(b"fLaC" + b"\x00" * 64)
            (root / "pending.ncm").write_bytes(b"source")
            (root / "normal.mp3").write_bytes(b"audio")
            ignored = root / "node_modules"
            ignored.mkdir()
            (ignored / "ignored.ncm").write_bytes(b"source")

            db = LibraryDB(str(Path(tmp) / "state.sqlite3"))
            settings = AppSettings(music_library_path=str(root))
            progress = scan_library(db, str(root), settings)
            library_id = db.get_selected_library()["id"]

            counts = db.counts_by_status(library_id)
            self.assertEqual(progress.ncm_found, 2)
            self.assertEqual(counts[FileStatus.CONVERTED.value], 1)
            self.assertEqual(counts[FileStatus.PENDING.value], 1)
            self.assertEqual(counts[FileStatus.NORMAL.value], 2)
            self.assertEqual(counts["all"], 4)

            (root / "pending.ncm").unlink()
            scan_library(db, str(root), settings)
            record = db.get_file_by_relative(library_id, "pending.ncm")
            self.assertEqual(record.status, FileStatus.MISSING.value)

    def test_incremental_scan_skips_unchanged_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "music"
            root.mkdir()
            (root / "track.ncm").write_bytes(b"source")
            db = LibraryDB(str(Path(tmp) / "state.sqlite3"))
            settings = AppSettings(music_library_path=str(root))
            scan_library(db, str(root), settings)
            library_id = db.get_selected_library()["id"]
            first = db.get_file_by_relative(library_id, "track.ncm")

            progress = scan_library(db, str(root), settings)
            second = db.get_file_by_relative(library_id, "track.ncm")

            self.assertEqual(progress.unchanged, 1)
            self.assertEqual(progress.added, 0)
            self.assertEqual(progress.updated, 0)
            self.assertEqual(second.last_scan_at, first.last_scan_at)

    def test_incremental_scan_updates_when_source_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "music"
            root.mkdir()
            source = root / "track.ncm"
            source.write_bytes(b"source")
            db = LibraryDB(str(Path(tmp) / "state.sqlite3"))
            settings = AppSettings(music_library_path=str(root))
            scan_library(db, str(root), settings)
            library_id = db.get_selected_library()["id"]
            record = db.get_file_by_relative(library_id, "track.ncm")
            db.update_file_status(record.id, FileStatus.FAILED.value, failure_reason="bad file")

            source.write_bytes(b"changed source")
            changed_time = time.time() + 2
            os.utime(source, (changed_time, changed_time))
            progress = scan_library(db, str(root), settings)
            record = db.get_file_by_relative(library_id, "track.ncm")

            self.assertEqual(progress.updated, 1)
            self.assertEqual(record.status, FileStatus.PENDING.value)
            self.assertEqual(record.failure_reason, "")

    def test_deleted_output_marks_converted_ncm_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "music"
            root.mkdir()
            (root / "track.ncm").write_bytes(b"source")
            output = root / "track.flac"
            output.write_bytes(b"fLaC" + b"\x00" * 64)
            db = LibraryDB(str(Path(tmp) / "state.sqlite3"))
            settings = AppSettings(music_library_path=str(root))
            scan_library(db, str(root), settings)
            library_id = db.get_selected_library()["id"]
            record = db.get_file_by_relative(library_id, "track.ncm")
            self.assertEqual(record.status, FileStatus.CONVERTED.value)

            output.unlink()
            progress = scan_library(db, str(root), settings)
            record = db.get_file_by_relative(library_id, "track.ncm")

            self.assertEqual(progress.updated, 1)
            self.assertEqual(record.status, FileStatus.PENDING.value)
            self.assertEqual(record.output_path, "")

    def test_missing_is_marked_once_and_full_rescan_clears_stale_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "music"
            root.mkdir()
            source = root / "old.ncm"
            source.write_bytes(b"source")
            db = LibraryDB(str(Path(tmp) / "state.sqlite3"))
            settings = AppSettings(music_library_path=str(root))
            scan_library(db, str(root), settings)
            library_id = db.get_selected_library()["id"]

            source.unlink()
            progress = scan_library(db, str(root), settings)
            record = db.get_file_by_relative(library_id, "old.ncm")
            self.assertEqual(progress.missing, 1)
            self.assertEqual(record.status, FileStatus.MISSING.value)

            progress = scan_library(db, str(root), settings)
            self.assertEqual(progress.missing, 0)

            scan_library(db, str(root), settings, scan_mode="full")
            self.assertIsNone(db.get_file_by_relative(library_id, "old.ncm"))

    def test_failed_status_is_retained_until_source_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "music"
            root.mkdir()
            source = root / "broken.ncm"
            source.write_bytes(b"source")
            db = LibraryDB(str(Path(tmp) / "state.sqlite3"))
            settings = AppSettings(music_library_path=str(root))
            scan_library(db, str(root), settings)
            library_id = db.get_selected_library()["id"]
            record = db.get_file_by_relative(library_id, "broken.ncm")
            db.update_file_status(record.id, FileStatus.FAILED.value, failure_reason="bad file")

            scan_library(db, str(root), settings)
            record = db.get_file_by_relative(library_id, "broken.ncm")
            self.assertEqual(record.status, FileStatus.FAILED.value)
            self.assertEqual(record.failure_reason, "bad file")

            source.write_bytes(b"changed source")
            scan_library(db, str(root), settings)
            record = db.get_file_by_relative(library_id, "broken.ncm")
            self.assertEqual(record.status, FileStatus.PENDING.value)
            self.assertEqual(record.failure_reason, "")

    def test_strict_scan_stores_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "music"
            root.mkdir()
            (root / "strict.ncm").write_bytes(b"source")
            db = LibraryDB(str(Path(tmp) / "state.sqlite3"))
            settings = AppSettings(music_library_path=str(root), strict_verification=True)
            scan_library(db, str(root), settings)
            library_id = db.get_selected_library()["id"]
            record = db.get_file_by_relative(library_id, "strict.ncm")
            self.assertIsNotNone(record.strict_hash)
            self.assertTrue(record.fingerprint.startswith("sha256:"))

    def test_conversion_queue_converts_pending_and_records_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "music"
            root.mkdir()
            (root / "track.ncm").write_bytes(b"source")
            (root / "skip.mp3").write_bytes(b"normal")
            db = LibraryDB(str(Path(tmp) / "state.sqlite3"))
            settings = AppSettings(music_library_path=str(root))
            scan_library(db, str(root), settings)
            library_id = db.get_selected_library()["id"]

            def fake_dump(input_path, output_path=None, skip=True, **kwargs):
                target = output_path(input_path, {"format": "flac"})
                Path(target).write_bytes(b"fLaC" + b"\x00" * 64)
                progress = kwargs.get("progress_callback")
                if progress:
                    progress(1, 1, target)
                return target

            queue = ConversionQueue(db, dump_func=fake_dump)
            progress = queue.run_pending(library_id, str(root), settings)
            self.assertEqual(progress.success, 1)
            self.assertEqual(progress.failed, 0)

            record = db.get_file_by_relative(library_id, "track.ncm")
            self.assertEqual(record.status, FileStatus.CONVERTED.value)
            self.assertTrue(Path(record.output_path).exists())
            history = db.list_history(library_id)
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["status"], "success")

    def test_conversion_queue_marks_failure_and_retry_can_succeed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "music"
            root.mkdir()
            (root / "track.ncm").write_bytes(b"source")
            db = LibraryDB(str(Path(tmp) / "state.sqlite3"))
            settings = AppSettings(music_library_path=str(root))
            scan_library(db, str(root), settings)
            library_id = db.get_selected_library()["id"]

            def failing_dump(*args, **kwargs):
                raise RuntimeError("output folder unavailable")

            progress = ConversionQueue(db, dump_func=failing_dump).run_pending(library_id, str(root), settings)
            self.assertEqual(progress.failed, 1)
            record = db.get_file_by_relative(library_id, "track.ncm")
            self.assertEqual(record.status, FileStatus.FAILED.value)
            self.assertIn("output folder", record.failure_reason.lower())

            db.update_file_status(record.id, FileStatus.PENDING.value, failure_reason="")

            def successful_dump(input_path, output_path=None, skip=True, **kwargs):
                target = output_path(input_path, {"format": "flac"})
                Path(target).write_bytes(b"fLaC" + b"\x00" * 64)
                return target

            progress = ConversionQueue(db, dump_func=successful_dump).run_pending(library_id, str(root), settings)
            self.assertEqual(progress.success, 1)
            record = db.get_file_by_relative(library_id, "track.ncm")
            self.assertEqual(record.status, FileStatus.CONVERTED.value)


if __name__ == "__main__":
    unittest.main()
