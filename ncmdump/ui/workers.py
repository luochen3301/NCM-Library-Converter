from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal, Slot

from ncmdump.audio_transcoder import FlacMp3Job, FlacMp3Options, transcode_flac_batch
from ncmdump.conversion_queue import ConversionQueue
from ncmdump.library_db import LibraryDB
from ncmdump.library_scanner import scan_library
from ncmdump.models import AppSettings


class ScanWorker(QObject):
    progressChanged = Signal(object)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        db_path: str,
        library_path: str,
        settings: AppSettings,
        scan_mode: str = "incremental",
        skip_unstable: bool = False,
    ) -> None:
        super().__init__()
        self.db_path = db_path
        self.library_path = library_path
        self.settings = settings
        self.scan_mode = scan_mode
        self.skip_unstable = skip_unstable
        self.cancel_event = threading.Event()

    @Slot()
    def cancel(self) -> None:
        self.cancel_event.set()

    @Slot()
    def run(self) -> None:
        try:
            db = LibraryDB(self.db_path)
            progress = scan_library(
                db,
                self.library_path,
                self.settings,
                cancel_event=self.cancel_event,
                progress_callback=self.progressChanged.emit,
                scan_mode=self.scan_mode,
                skip_unstable=self.skip_unstable,
            )
            self.finished.emit(progress)
        except BaseException as exc:
            self.failed.emit(str(exc))


class ConversionWorker(QObject):
    progressChanged = Signal(object)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        db_path: str,
        library_id: int,
        library_path: str,
        settings: AppSettings,
        file_ids: list[int] | None,
    ) -> None:
        super().__init__()
        self.db_path = db_path
        self.library_id = library_id
        self.library_path = library_path
        self.settings = settings
        self.file_ids = list(file_ids) if file_ids is not None else None
        self.queue: ConversionQueue | None = None
        self._pause_requested = False
        self._cancel_requested = False

    @Slot()
    def pause(self) -> None:
        self._pause_requested = True
        if self.queue is not None:
            self.queue.pause()

    @Slot()
    def resume(self) -> None:
        self._pause_requested = False
        if self.queue is not None:
            self.queue.resume()

    @Slot()
    def cancel(self) -> None:
        self._cancel_requested = True
        if self.queue is not None:
            self.queue.cancel()

    @Slot()
    def run(self) -> None:
        try:
            db = LibraryDB(self.db_path)
            self.queue = ConversionQueue(db)
            if self._pause_requested:
                self.queue.pause()
            if self._cancel_requested:
                self.queue.cancel()
            if self.file_ids is None:
                progress = self.queue.run_pending(
                    self.library_id,
                    self.library_path,
                    self.settings,
                    self.progressChanged.emit,
                )
            else:
                progress = self.queue.run_file_ids(
                    self.library_id,
                    self.library_path,
                    self.settings,
                    self.file_ids,
                    self.progressChanged.emit,
                )
            self.finished.emit(progress)
        except BaseException as exc:
            self.failed.emit(str(exc))


class FlacMp3Worker(QObject):
    progressChanged = Signal(object)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, jobs: list[FlacMp3Job], options: FlacMp3Options) -> None:
        super().__init__()
        self.jobs = list(jobs)
        self.options = options
        self.cancel_event = threading.Event()

    @Slot()
    def cancel(self) -> None:
        self.cancel_event.set()

    @Slot()
    def run(self) -> None:
        try:
            progress = transcode_flac_batch(
                self.jobs,
                self.options,
                cancel_event=self.cancel_event,
                progress_callback=self.progressChanged.emit,
            )
            self.finished.emit(progress)
        except BaseException as exc:
            self.failed.emit(str(exc))


__all__ = ["ConversionWorker", "FlacMp3Worker", "ScanWorker"]
