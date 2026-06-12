from __future__ import annotations

import os
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Callable, Iterable

from . import dump
from .library_db import LibraryDB
from .models import (
    AppSettings,
    FileRecord,
    FileStatus,
    QueueProgress,
    friendly_error_message,
    is_reasonable_output,
    make_output_path_factory,
)


QueueProgressCallback = Callable[[QueueProgress], None]


class ConversionCanceled(RuntimeError):
    pass


class ConversionQueue:
    def __init__(self, db: LibraryDB, dump_func: Callable = dump):
        self.db = db
        self.dump_func = dump_func
        self.pause_event = threading.Event()
        self.pause_event.set()
        self.cancel_event = threading.Event()
        self._lock = threading.Lock()
        self.progress = QueueProgress()

    def pause(self) -> None:
        self.pause_event.clear()
        with self._lock:
            self.progress.paused = True

    def resume(self) -> None:
        self.pause_event.set()
        with self._lock:
            self.progress.paused = False

    def cancel(self) -> None:
        self.cancel_event.set()
        self.pause_event.set()
        with self._lock:
            self.progress.canceled = True

    def reset(self) -> None:
        self.cancel_event.clear()
        self.pause_event.set()
        self.progress = QueueProgress()

    def run_pending(
        self,
        library_id: int,
        library_path: str,
        settings: AppSettings,
        progress_callback: QueueProgressCallback | None = None,
    ) -> QueueProgress:
        return self.run_records(
            library_id,
            library_path,
            settings,
            self.db.list_pending_files(library_id),
            progress_callback,
        )

    def run_file_ids(
        self,
        library_id: int,
        library_path: str,
        settings: AppSettings,
        file_ids: Iterable[int],
        progress_callback: QueueProgressCallback | None = None,
    ) -> QueueProgress:
        records = self.db.list_files_by_ids(file_ids)
        return self.run_records(library_id, library_path, settings, records, progress_callback)

    def run_records(
        self,
        library_id: int,
        library_path: str,
        settings: AppSettings,
        records: Iterable[FileRecord],
        progress_callback: QueueProgressCallback | None = None,
    ) -> QueueProgress:
        self.reset()
        work = [record for record in records if record.status in {FileStatus.PENDING.value, FileStatus.FAILED.value}]
        with self._lock:
            self.progress.total = len(work)
            self.progress.remaining = len(work)
        self._emit(progress_callback)
        if not work:
            return self.progress

        max_workers = max(1, int(settings.max_concurrent_conversions or 2))
        self.db.add_log("INFO", "conversion", f"Starting conversion queue with {len(work)} files")

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            pending = {}
            iterator = iter(work)
            while not self.cancel_event.is_set():
                while len(pending) < max_workers:
                    try:
                        record = next(iterator)
                    except StopIteration:
                        break
                    future = executor.submit(
                        self._convert_one,
                        library_id,
                        library_path,
                        settings,
                        record,
                        progress_callback,
                    )
                    pending[future] = record
                if not pending:
                    break
                done, _ = wait(pending.keys(), return_when=FIRST_COMPLETED, timeout=0.2)
                for future in done:
                    pending.pop(future, None)
                    try:
                        future.result()
                    except ConversionCanceled:
                        self.cancel()
                    except Exception as exc:
                        self.db.add_log("ERROR", "conversion", f"Queue worker failed: {exc}")

            if self.cancel_event.is_set():
                for future in pending:
                    future.cancel()

        with self._lock:
            self.progress.canceled = self.cancel_event.is_set()
            self.progress.remaining = max(0, self.progress.total - self.progress.success - self.progress.failed)
            self.progress.message = "Conversion canceled" if self.progress.canceled else "Conversion finished"
        self.db.add_log("INFO", "conversion", self.progress.message)
        self._emit(progress_callback)
        return self.progress

    def _convert_one(
        self,
        library_id: int,
        library_path: str,
        settings: AppSettings,
        record: FileRecord,
        progress_callback: QueueProgressCallback | None,
    ) -> None:
        self._wait_if_paused()
        if self.cancel_event.is_set():
            raise ConversionCanceled()

        started = time.monotonic()
        output_path = ""
        with self._lock:
            self.progress.current_index += 1
            self.progress.current_file = record.relative_path
            self.progress.message = f"Converting {record.relative_path}"
        self._emit(progress_callback)

        try:
            if not Path(record.absolute_path).exists():
                raise FileNotFoundError(record.absolute_path)

            output_factory = make_output_path_factory(record.absolute_path, library_path, settings)
            output_path = self._call_dump(record, output_factory, settings, progress_callback)
            if not is_reasonable_output(output_path):
                raise RuntimeError("Conversion finished but output file was not created.")

            if settings.delete_source_after_success:
                try:
                    os.remove(record.absolute_path)
                except OSError as exc:
                    self.db.add_log("WARNING", "conversion", f"Could not delete source {record.absolute_path}: {exc}")

            duration_ms = int((time.monotonic() - started) * 1000)
            self.db.update_file_status(record.id, FileStatus.CONVERTED.value, output_path=output_path, failure_reason="")
            self.db.add_history(
                record.id,
                library_id,
                record.absolute_path,
                output_path,
                record.fingerprint,
                "success",
                duration_ms=duration_ms,
            )
            with self._lock:
                self.progress.success += 1
                self.progress.remaining = max(0, self.progress.total - self.progress.success - self.progress.failed)
                self.progress.message = f"Converted {record.relative_path}"
            self.db.add_log("INFO", "conversion", f"Converted {record.absolute_path} -> {output_path}")
        except ConversionCanceled:
            raise
        except Exception as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            message = friendly_error_message(exc)
            self.db.update_file_status(record.id, FileStatus.FAILED.value, output_path=output_path, failure_reason=message)
            self.db.add_history(
                record.id,
                library_id,
                record.absolute_path,
                output_path,
                record.fingerprint,
                "failed",
                error_message=message,
                duration_ms=duration_ms,
            )
            with self._lock:
                self.progress.failed += 1
                self.progress.remaining = max(0, self.progress.total - self.progress.success - self.progress.failed)
                self.progress.message = message
            self.db.add_log("ERROR", "conversion", f"Failed {record.absolute_path}: {message}")
        finally:
            self._emit(progress_callback)

    def _call_dump(
        self,
        record: FileRecord,
        output_factory: Callable,
        settings: AppSettings,
        progress_callback: QueueProgressCallback | None,
    ) -> str:
        def pause_callback() -> bool:
            return not self.pause_event.is_set()

        def cancel_callback() -> bool:
            return self.cancel_event.is_set()

        def file_progress(written: int, total: int, _: str) -> None:
            with self._lock:
                if total:
                    percent = int((written / total) * 100)
                    self.progress.message = f"{record.relative_path} {percent}%"
            self._emit(progress_callback)

        try:
            return self.dump_func(
                record.absolute_path,
                output_path=output_factory,
                skip=settings.skip_existing_output,
                progress_callback=file_progress,
                pause_callback=pause_callback,
                cancel_callback=cancel_callback,
            )
        except TypeError:
            return self.dump_func(
                record.absolute_path,
                output_path=output_factory,
                skip=settings.skip_existing_output,
            )

    def _wait_if_paused(self) -> None:
        while not self.pause_event.wait(0.2):
            if self.cancel_event.is_set():
                raise ConversionCanceled()

    def _emit(self, progress_callback: QueueProgressCallback | None) -> None:
        if progress_callback:
            with self._lock:
                snapshot = QueueProgress(**self.progress.__dict__)
            progress_callback(snapshot)
