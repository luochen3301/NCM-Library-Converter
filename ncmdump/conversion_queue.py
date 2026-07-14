from __future__ import annotations

import copy
import inspect
import os
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Iterable

from . import dump
from .core import NCMConversionCanceled, is_valid_audio_output
from .library_db import LibraryDB
from .models import (
    ActiveConversion,
    AppSettings,
    FileRecord,
    FileStatus,
    QueueProgress,
    TaskState,
    candidate_output_paths,
    friendly_error_message,
    make_output_path_factory,
)


QueueProgressCallback = Callable[[QueueProgress], None]

# Public compatibility name. Core and queue now share one dedicated exception,
# so cancellation can never be mistaken for an ordinary failed conversion.
ConversionCanceled = NCMConversionCanceled


class ConversionQueue:
    """Run conversion work with reliable cancellation and aggregate progress."""

    EMIT_INTERVAL_SECONDS = 0.1

    def __init__(self, db: LibraryDB, dump_func: Callable = dump):
        self.db = db
        self.dump_func = dump_func
        self.pause_event = threading.Event()
        self.pause_event.set()
        self.cancel_event = threading.Event()
        self._lock = threading.RLock()
        self._emit_lock = threading.RLock()
        self._run_guard = threading.Lock()
        self._is_running = False
        self._active: dict[str, ActiveConversion] = {}
        self._progress_callback: QueueProgressCallback | None = None
        self._last_emit_at = 0.0
        self.progress = QueueProgress()

        # Inspect once. A TypeError raised by the conversion function itself is
        # a real failure and must never trigger a second invocation.
        try:
            self._dump_signature = inspect.signature(dump_func)
            parameters = self._dump_signature.parameters.values()
            self._dump_accepts_var_kwargs = any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters
            )
            self._dump_keyword_names = {
                parameter.name
                for parameter in self._dump_signature.parameters.values()
                if parameter.kind
                in {inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY}
            }
            self._dump_signature_error: Exception | None = None
        except (TypeError, ValueError) as exc:
            self._dump_signature = None
            self._dump_accepts_var_kwargs = False
            self._dump_keyword_names = set()
            self._dump_signature_error = exc

    def pause(self) -> None:
        self.pause_event.clear()
        with self._lock:
            self.progress.paused = True
            self.progress.state = TaskState.PAUSED
            self.progress.message = "Conversion paused"
        self._emit(force=True)

    def resume(self) -> None:
        self.pause_event.set()
        with self._lock:
            self.progress.paused = False
            self.progress.state = TaskState.CONVERTING if self._is_running else TaskState.IDLE
            self.progress.message = "Conversion resumed" if self._is_running else ""
        self._emit(force=True)

    def cancel(self) -> None:
        self.cancel_event.set()
        # Wake workers paused in Event.wait so they can observe cancellation.
        self.pause_event.set()
        with self._lock:
            self.progress.paused = False
            self.progress.canceled = True
            self.progress.state = TaskState.CANCELING
            self.progress.message = "Canceling conversion"
        self._emit(force=True)

    def reset(self) -> None:
        """Explicitly prepare a previously canceled queue for another run."""

        with self._lock:
            if self._is_running:
                raise RuntimeError("Cannot reset a running conversion queue.")
            self.cancel_event.clear()
            self.pause_event.set()
            self._active.clear()
            self._last_emit_at = 0.0
            self.progress = QueueProgress(state=TaskState.IDLE)

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
        if self._dump_signature_error is not None:
            raise TypeError(f"Conversion callable signature cannot be inspected: {self._dump_signature_error}")
        if not self._run_guard.acquire(blocking=False):
            raise RuntimeError("This conversion queue is already running.")

        try:
            # Freeze user-editable inputs for the lifetime of this task.
            settings_snapshot = copy.deepcopy(settings)
            library_path_snapshot = os.fspath(library_path)
            work = [
                record
                for record in list(records)
                if record.status in {FileStatus.PENDING.value, FileStatus.FAILED.value}
            ]

            with self._lock:
                self._is_running = True
                self._progress_callback = progress_callback
                self._active.clear()
                self._last_emit_at = 0.0
                canceled_before_start = self.cancel_event.is_set()
                paused_before_start = not self.pause_event.is_set()
                initial_state = (
                    TaskState.CANCELING
                    if canceled_before_start
                    else TaskState.PAUSED
                    if paused_before_start
                    else TaskState.CONVERTING
                )
                self.progress = QueueProgress(
                    state=initial_state,
                    total=len(work),
                    remaining=len(work),
                    paused=paused_before_start,
                    canceled=canceled_before_start,
                    message="Canceling conversion" if canceled_before_start else "Starting conversion",
                )
            self._emit(progress_callback, force=True)

            if canceled_before_start:
                self._finish_run(canceled=True, message="Conversion canceled")
                return self.progress
            if not work:
                self._finish_run(canceled=False, message="No files need conversion")
                return self.progress

            max_workers = max(1, int(settings_snapshot.max_concurrent_conversions or 2))
            self.db.add_log("INFO", "conversion", f"Starting conversion queue with {len(work)} files")
            try:
                self._run_executor(
                    library_id,
                    library_path_snapshot,
                    settings_snapshot,
                    work,
                    max_workers,
                    progress_callback,
                )
            except NCMConversionCanceled:
                self.cancel()

            canceled = self.cancel_event.is_set()
            message = "Conversion canceled" if canceled else "Conversion finished"
            self._finish_run(canceled=canceled, message=message)
            self.db.add_log("INFO", "conversion", message)
            return self.progress
        finally:
            with self._lock:
                self._is_running = False
                self._progress_callback = None
            self._run_guard.release()

    def _run_executor(
        self,
        library_id: int,
        library_path: str,
        settings: AppSettings,
        work: list[FileRecord],
        max_workers: int,
        progress_callback: QueueProgressCallback | None,
    ) -> None:
        iterator = iter(work)
        exhausted = False
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            pending: dict[Any, FileRecord] = {}
            while not self.cancel_event.is_set():
                self._wait_if_paused()
                if self.cancel_event.is_set():
                    break

                while len(pending) < max_workers and not exhausted and not self.cancel_event.is_set():
                    try:
                        record = next(iterator)
                    except StopIteration:
                        exhausted = True
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
                    if exhausted:
                        break
                    continue

                done, _ = wait(pending.keys(), return_when=FIRST_COMPLETED, timeout=0.2)
                for future in done:
                    pending.pop(future, None)
                    try:
                        future.result()
                    except NCMConversionCanceled:
                        self.cancel()
                    except Exception as exc:
                        # _convert_one normally contains worker failures. This is
                        # reserved for infrastructure/DB failures that escaped it.
                        self.db.add_log("ERROR", "conversion", f"Queue worker failed: {exc}")

            if self.cancel_event.is_set():
                for future in pending:
                    future.cancel()

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
            raise NCMConversionCanceled("Conversion canceled")

        started = time.monotonic()
        output_path = ""
        chosen_output: dict[str, str] = {"path": ""}
        activity_key = self._activity_key(record)
        prior_outputs = self._capture_candidate_outputs(record, library_path, settings)

        with self._lock:
            self.progress.current_index += 1
            self.progress.current_file = record.relative_path
            self.progress.message = f"Converting {record.relative_path}"
            self._active[activity_key] = ActiveConversion(
                file_id=record.id,
                relative_path=record.relative_path,
            )
            self._recompute_progress_locked()
        self._emit(progress_callback, force=True)

        try:
            if not Path(record.absolute_path).exists():
                raise FileNotFoundError(record.absolute_path)

            output_factory = make_output_path_factory(record.absolute_path, library_path, settings)

            def tracked_output_factory(path: str, metadata: dict[str, Any]) -> str:
                target = os.fspath(output_factory(path, metadata))
                chosen_output["path"] = target
                return target

            output_path = self._call_dump(
                record,
                tracked_output_factory,
                settings,
                activity_key,
                progress_callback,
            )
            if self.cancel_event.is_set():
                self._cleanup_new_outputs(prior_outputs, only_path=output_path)
                raise NCMConversionCanceled("Conversion canceled")
            if not is_valid_audio_output(output_path):
                raise RuntimeError(
                    "Conversion finished but the output is not a valid MP3 or FLAC file."
                )

            skipped = settings.skip_existing_output and self._matches_prior_output(
                output_path, prior_outputs
            )
            result = "skipped" if skipped else "converted"
            history_status = "skipped" if skipped else "success"
            duration_ms = int((time.monotonic() - started) * 1000)
            self._record_result(
                record,
                library_id,
                output_path,
                history_status,
                duration_ms=duration_ms,
            )

            if settings.delete_source_after_success:
                self._delete_source_after_persisted_result(record)

            with self._lock:
                self._active.pop(activity_key, None)
                self.progress.completed += 1
                if result == "skipped":
                    self.progress.skipped += 1
                    self.progress.message = f"Skipped existing output for {record.relative_path}"
                else:
                    self.progress.converted += 1
                    self.progress.message = f"Converted {record.relative_path}"
                self._recompute_progress_locked()
            self.db.add_log(
                "INFO",
                "conversion",
                f"{'Skipped' if skipped else 'Converted'} {record.absolute_path} -> {output_path}",
            )
            self._emit(progress_callback, force=True)
        except NCMConversionCanceled:
            self._cleanup_new_outputs(
                prior_outputs,
                only_path=chosen_output["path"],
            )
            with self._lock:
                self.cancel_event.set()
                self.progress.canceled = True
                self.progress.state = TaskState.CANCELING
                self.progress.message = "Canceling conversion"
                self._active.pop(activity_key, None)
                self._recompute_progress_locked()
            self._emit(progress_callback, force=True)
            raise
        except Exception as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            message = friendly_error_message(exc)
            try:
                self._record_result(
                    record,
                    library_id,
                    output_path,
                    "failed",
                    error_message=message,
                    duration_ms=duration_ms,
                )
            except Exception as persistence_error:
                self.db.add_log(
                    "ERROR",
                    "conversion",
                    f"Could not persist failed result for {record.absolute_path}: {persistence_error}",
                )
            with self._lock:
                self._active.pop(activity_key, None)
                self.progress.completed += 1
                self.progress.failed += 1
                self.progress.message = message
                self._recompute_progress_locked()
            self.db.add_log("ERROR", "conversion", f"Failed {record.absolute_path}: {message}")
            self._emit(progress_callback, force=True)

    def _call_dump(
        self,
        record: FileRecord,
        output_factory: Callable,
        settings: AppSettings,
        activity_key: str,
        progress_callback: QueueProgressCallback | None,
    ) -> str:
        def pause_callback() -> bool:
            return not self.pause_event.is_set()

        def cancel_callback() -> bool:
            return self.cancel_event.is_set()

        def file_progress(written: int, total: int, _: str) -> None:
            safe_written = max(0, int(written or 0))
            safe_total = max(0, int(total or 0))
            with self._lock:
                item = self._active.get(activity_key)
                if item is None:
                    return
                item.written = safe_written
                item.total = safe_total
                item.percent = (
                    min(100.0, max(0.0, safe_written * 100.0 / safe_total))
                    if safe_total
                    else 0.0
                )
                self.progress.message = f"{record.relative_path} {item.percent:.0f}%"
                self._recompute_progress_locked()
            self._emit(
                progress_callback,
                force=bool(safe_total and safe_written >= safe_total),
            )

        available = {
            "output_path": output_factory,
            "skip": settings.skip_existing_output,
            "progress_callback": file_progress,
            "pause_callback": pause_callback,
            "cancel_callback": cancel_callback,
        }
        kwargs = {
            name: value
            for name, value in available.items()
            if self._dump_accepts_var_kwargs or name in self._dump_keyword_names
        }
        # Exactly one call. In particular, TypeError from inside dump_func is
        # not interpreted as evidence that callbacks are unsupported.
        return os.fspath(self.dump_func(record.absolute_path, **kwargs))

    def _record_result(
        self,
        record: FileRecord,
        library_id: int,
        output_path: str,
        history_status: str,
        *,
        error_message: str = "",
        duration_ms: int = 0,
    ) -> None:
        atomic_helper = getattr(self.db, "record_conversion_result", None)
        source_deleted = False if history_status in {"success", "skipped"} else None
        if callable(atomic_helper):
            atomic_helper(
                record.id,
                library_id,
                record.absolute_path,
                output_path,
                record.fingerprint,
                history_status,
                error_message,
                duration_ms,
                source_deleted=source_deleted,
            )
            return

        # Backward-compatible fallback for older LibraryDB implementations.
        file_status = (
            FileStatus.CONVERTED.value
            if history_status in {"success", "skipped"}
            else FileStatus.FAILED.value
        )
        if record.id is not None:
            self.db.update_file_status(
                record.id,
                file_status,
                output_path=output_path,
                failure_reason=error_message,
            )
        self.db.add_history(
            record.id,
            library_id,
            record.absolute_path,
            output_path,
            record.fingerprint,
            history_status,
            error_message=error_message,
            duration_ms=duration_ms,
        )

    def _delete_source_after_persisted_result(self, record: FileRecord) -> None:
        marker = getattr(self.db, "set_source_deleted", None)
        marked = False
        if callable(marker) and record.id is not None:
            try:
                marker(record.id, True)
                marked = True
            except Exception as exc:
                # Without a durable intent marker a subsequent scan could
                # misclassify our deletion as an unexpected missing source.
                self.db.add_log(
                    "WARNING",
                    "conversion",
                    f"Source was kept because delete intent could not be recorded: {exc}",
                )
                return

        try:
            os.remove(record.absolute_path)
        except FileNotFoundError:
            # The desired postcondition already holds; retain the marker.
            return
        except OSError as exc:
            if marked:
                try:
                    marker(record.id, False)
                except Exception as marker_error:
                    self.db.add_log(
                        "ERROR",
                        "conversion",
                        f"Could not clear source-delete intent for {record.absolute_path}: {marker_error}",
                    )
            self.db.add_log(
                "WARNING",
                "conversion",
                f"Could not delete source {record.absolute_path}: {exc}",
            )

    def _wait_if_paused(self) -> None:
        while not self.pause_event.wait(0.2):
            if self.cancel_event.is_set():
                raise NCMConversionCanceled("Conversion canceled")
        if self.cancel_event.is_set():
            raise NCMConversionCanceled("Conversion canceled")

    def _finish_run(self, *, canceled: bool, message: str) -> None:
        with self._lock:
            self._active.clear()
            self.progress.canceled = canceled
            self.progress.paused = False
            self.progress.not_processed = (
                max(0, self.progress.total - self.progress.completed) if canceled else 0
            )
            self.progress.remaining = max(0, self.progress.total - self.progress.completed)
            if not canceled and self.progress.completed >= self.progress.total:
                self.progress.overall_percent = 100.0
                self.progress.remaining = 0
            elif not self.progress.total:
                self.progress.overall_percent = 100.0
                self.progress.remaining = 0
            self.progress.state = TaskState.IDLE
            self.progress.message = message
            self._sync_active_items_locked()
        self._emit(force=True)

    def _recompute_progress_locked(self) -> None:
        self.progress.remaining = max(0, self.progress.total - self.progress.completed)
        if self.progress.total:
            active_fraction = sum(
                min(1.0, max(0.0, item.written / item.total))
                for item in self._active.values()
                if item.total > 0
            )
            calculated = (self.progress.completed + active_fraction) * 100.0 / self.progress.total
            self.progress.overall_percent = max(
                float(self.progress.overall_percent),
                min(100.0, calculated),
            )
        self._sync_active_items_locked()

    def _sync_active_items_locked(self) -> None:
        self.progress.active_items = [replace(item) for item in self._active.values()]

    def _emit(
        self,
        progress_callback: QueueProgressCallback | None = None,
        *,
        force: bool = False,
    ) -> None:
        callback = progress_callback or self._progress_callback
        if callback is None:
            return

        with self._emit_lock:
            now = time.monotonic()
            if not force and now - self._last_emit_at < self.EMIT_INTERVAL_SECONDS:
                return
            with self._lock:
                self.progress.sequence += 1
                snapshot = copy.deepcopy(self.progress)
                self._last_emit_at = now
            try:
                callback(snapshot)
            except Exception:
                # UI callbacks must not be able to corrupt conversion results.
                pass

    @staticmethod
    def _activity_key(record: FileRecord) -> str:
        return f"{record.id!r}:{os.path.normcase(os.path.abspath(record.absolute_path))}"

    @staticmethod
    def _path_key(path: str | os.PathLike[str]) -> str:
        return os.path.normcase(os.path.abspath(os.fspath(path)))

    def _capture_candidate_outputs(
        self,
        record: FileRecord,
        library_path: str,
        settings: AppSettings,
    ) -> dict[str, dict[str, Any]]:
        states: dict[str, dict[str, Any]] = {}
        for candidate in candidate_output_paths(
            record.absolute_path,
            library_path,
            settings,
            known_output_path=record.output_path,
        ):
            key = self._path_key(candidate)
            try:
                stat = os.stat(candidate)
            except OSError:
                states[key] = {
                    "path": os.fspath(candidate),
                    "exists": False,
                    "valid": False,
                }
                continue
            states[key] = {
                "path": os.fspath(candidate),
                "exists": True,
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "inode": stat.st_ino,
                "valid": is_valid_audio_output(candidate),
            }
        return states

    def _matches_prior_output(
        self,
        output_path: str,
        states: dict[str, dict[str, Any]],
    ) -> bool:
        state = states.get(self._path_key(output_path))
        if not state or not state["exists"] or not state["valid"]:
            return False
        try:
            stat = os.stat(output_path)
        except OSError:
            return False
        return (
            stat.st_size,
            stat.st_mtime_ns,
            stat.st_ino,
        ) == (
            state["size"],
            state["mtime_ns"],
            state["inode"],
        )

    def _cleanup_new_outputs(
        self,
        prior_outputs: dict[str, dict[str, Any]],
        *,
        only_path: str = "",
    ) -> None:
        if only_path:
            candidates = [only_path]
        else:
            candidates = []
        for candidate in candidates:
            if not candidate:
                continue
            previous = prior_outputs.get(self._path_key(candidate))
            if previous and previous["exists"]:
                continue
            try:
                os.remove(candidate)
            except OSError:
                pass
