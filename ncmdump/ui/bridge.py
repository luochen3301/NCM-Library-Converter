from __future__ import annotations

import os
import time
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Iterable

from PySide6.QtCore import QFileSystemWatcher, QObject, Property, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QGuiApplication

from ncmdump.audio_transcoder import (
    FlacMp3Job,
    FlacMp3Options,
    FlacMp3Progress,
    FlacMp3Status,
    discover_flac_files,
    output_path_for,
)
from ncmdump.i18n import Translator
from ncmdump.language_classifier import LANGUAGE_ORDER, classify_path
from ncmdump.library_db import LibraryDB
from ncmdump.library_scanner import should_ignore_dir
from ncmdump.models import (
    DEFAULT_IGNORED_FOLDERS,
    AppSettings,
    FileRecord,
    FileStatus,
    QueueProgress,
    ScanProgress,
    TaskState,
)
from ncmdump.platform_integration import FileManagerStatus, open_folder, reveal_in_file_manager
from ncmdump.task_controller import TaskController, TaskTransitionError
from ncmdump.ui.qml_models import (
    ClassifiedRow,
    FlacTableModel,
    HistoryTableModel,
    LanguageTableModel,
    LibraryTableModel,
    MappingListModel,
)
from ncmdump.ui.workers import ConversionWorker, FlacMp3Worker, ScanWorker


PAGE_KEYS = {"library", "tasks", "history", "settings", "language", "flac_mp3"}
CONVERTIBLE_STATUSES = {FileStatus.PENDING.value, FileStatus.FAILED.value}


def _to_local_path(value: Any) -> str:
    if hasattr(value, "toLocalFile"):
        return str(value.toLocalFile())
    text = str(value or "")
    if text.startswith("file:"):
        return QUrl(text).toLocalFile()
    return text


def _plain_value(value: Any) -> Any:
    if hasattr(value, "toVariant"):
        return value.toVariant()
    return value


def _failure_group_key(message: str) -> str:
    lowered = (message or "").casefold()
    if any(token in lowered for token in ("permission", "access", "denied")):
        return "permission"
    if "output folder" in lowered or ("output" in lowered and "unavailable" in lowered):
        return "output"
    if any(token in lowered for token in ("does not exist", "not found", "moved", "no such file", "cannot find")):
        return "missing"
    if any(token in lowered for token in ("disk", "space", "full")):
        return "disk"
    if any(token in lowered for token in ("in use", "being used")):
        return "busy"
    if any(token in lowered for token in ("path too long", "too long", "file name", "filename", "invalid")):
        return "path"
    if any(token in lowered for token in ("format", "header", "decrypt", "metadata", "ncm")):
        return "format"
    return "other"


class ApplicationBridge(QObject):
    """The only desktop boundary between QML and the existing library services."""

    stateChanged = Signal()
    themeChanged = Signal()
    languageChanged = Signal()
    confirmationRequested = Signal(str, str, str, str, bool)
    toastRequested = Signal(str, str)
    dialogRequested = Signal(str, str, str)
    readyToClose = Signal()

    def __init__(self, db_path: str | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.db = LibraryDB(db_path)
        self.settings = self.db.get_settings()
        self._settings_draft = asdict(self.settings)
        self._settings_dirty = False
        self.translator = Translator(self.settings.language)
        self.task_controller = TaskController()
        self._current_page = "library"
        self.library_id: int | None = None
        self._library_search = ""
        self._library_status = "all"
        self._library_format = "all"
        self._history_search = ""
        self._history_status = "all"
        self._language_search = ""
        self._language_filter = "all"
        self._counts = {"all": 0, **{status.value: 0 for status in FileStatus}}
        self._task_progress = 0.0
        self._task_title = self._tr("progress.ready")
        self._task_detail = self._tr("progress.readyDetail")
        self._task_metrics = ""
        self._task_summary: dict[str, Any] = {}
        self._logs_text = ""
        self._i18n_revision = 0
        self._last_conversion_percent = 0.0
        self._conversion_started_at = 0.0
        self._allow_close = False
        self._close_waiting = False
        self._confirmation_serial = 0
        self._confirmations: dict[str, Callable[[bool], None]] = {}

        self.library_model = LibraryTableModel(self)
        self.queue_model = LibraryTableModel(self)
        self.history_model = HistoryTableModel(self)
        self.language_model = LanguageTableModel(self)
        self.flac_model = FlacTableModel(self)
        self.failure_group_model = MappingListModel(self)
        self.ignore_rule_model = MappingListModel(self)
        self.library_model.checkedChanged.connect(self._emit_state)
        self.queue_model.checkedChanged.connect(self._emit_state)

        self.scan_thread: QThread | None = None
        self.scan_worker: ScanWorker | None = None
        self.conversion_thread: QThread | None = None
        self.conversion_worker: ConversionWorker | None = None
        self.flac_thread: QThread | None = None
        self.flac_worker: FlacMp3Worker | None = None
        self._flac_sources: dict[str, dict[str, Any]] = {}

        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(self._on_watched_directory_changed)
        self._watch_rescan_timer = QTimer(self)
        self._watch_rescan_timer.setSingleShot(True)
        self._watch_rescan_timer.setInterval(1600)
        self._watch_rescan_timer.timeout.connect(lambda: self.startScan("incremental", True))

        self._sync_ignore_rules()
        QTimer.singleShot(0, self._load_initial_library)

    def _emit_state(self) -> None:
        self.stateChanged.emit()

    def _tr(self, key: str, **values: Any) -> str:
        return self.translator.t(key, **values)

    @Slot(str, result=str)
    @Slot(str, "QVariantMap", result=str)
    def translate(self, key: str, values: dict[str, Any] | None = None) -> str:
        try:
            return self.translator.t(key, **dict(_plain_value(values) or {}))
        except (KeyError, ValueError):
            return self.translator.t(key)

    @Property(QObject, constant=True)
    def libraryModel(self) -> QObject:  # noqa: N802 - QML API
        return self.library_model

    @Property(QObject, constant=True)
    def queueModel(self) -> QObject:  # noqa: N802
        return self.queue_model

    @Property(QObject, constant=True)
    def historyModel(self) -> QObject:  # noqa: N802
        return self.history_model

    @Property(QObject, constant=True)
    def languageModel(self) -> QObject:  # noqa: N802
        return self.language_model

    @Property(QObject, constant=True)
    def flacModel(self) -> QObject:  # noqa: N802
        return self.flac_model

    @Property(QObject, constant=True)
    def failureGroupModel(self) -> QObject:  # noqa: N802
        return self.failure_group_model

    @Property(QObject, constant=True)
    def ignoreRuleModel(self) -> QObject:  # noqa: N802
        return self.ignore_rule_model

    @Property(str, notify=stateChanged)
    def currentPage(self) -> str:  # noqa: N802
        return self._current_page

    @Property(str, notify=stateChanged)
    def pageTitle(self) -> str:  # noqa: N802
        return self._tr(f"nav.{self._current_page}")

    @Property(str, notify=stateChanged)
    def libraryPath(self) -> str:  # noqa: N802
        return self.settings.music_library_path

    @Property(str, notify=stateChanged)
    def libraryName(self) -> str:  # noqa: N802
        path = self.settings.music_library_path
        return (Path(path).name or path) if path else self._tr("nav.noLibrary")

    @Property(bool, notify=stateChanged)
    def hasLibrary(self) -> bool:  # noqa: N802
        return bool(self.library_id and self.settings.music_library_path)

    @Property("QVariantMap", notify=stateChanged)
    def counts(self) -> dict[str, int]:
        return dict(self._counts)

    @Property(str, notify=themeChanged)
    def theme(self) -> str:
        return str(self._settings_draft.get("theme") or "dark")

    @Property(str, notify=languageChanged)
    def language(self) -> str:
        return str(self._settings_draft.get("language") or "system")

    @Property(int, notify=languageChanged)
    def i18nRevision(self) -> int:  # noqa: N802
        return self._i18n_revision

    @Property(str, notify=stateChanged)
    def density(self) -> str:
        return str(self._settings_draft.get("density") or "comfortable")

    @Property("QVariantMap", notify=stateChanged)
    def settingsDraft(self) -> dict[str, Any]:  # noqa: N802
        return deepcopy(self._settings_draft)

    @Property(bool, notify=stateChanged)
    def settingsDirty(self) -> bool:  # noqa: N802
        return self._settings_dirty

    @Property(str, notify=stateChanged)
    def taskState(self) -> str:  # noqa: N802
        return self.task_controller.state.value

    @Property(bool, notify=stateChanged)
    def taskBusy(self) -> bool:  # noqa: N802
        return self.task_controller.busy

    @Property(float, notify=stateChanged)
    def taskProgress(self) -> float:  # noqa: N802
        return self._task_progress

    @Property(str, notify=stateChanged)
    def taskTitle(self) -> str:  # noqa: N802
        return self._task_title

    @Property(str, notify=stateChanged)
    def taskDetail(self) -> str:  # noqa: N802
        return self._task_detail

    @Property(str, notify=stateChanged)
    def taskMetrics(self) -> str:  # noqa: N802
        return self._task_metrics

    @Property("QVariantMap", notify=stateChanged)
    def taskSummary(self) -> dict[str, Any]:  # noqa: N802
        return dict(self._task_summary)

    @Property(str, notify=stateChanged)
    def logsText(self) -> str:  # noqa: N802
        return self._logs_text

    @Property(str, notify=stateChanged)
    def librarySearch(self) -> str:  # noqa: N802
        return self._library_search

    @Property(str, notify=stateChanged)
    def libraryStatusFilter(self) -> str:  # noqa: N802
        return self._library_status

    @Property(str, notify=stateChanged)
    def libraryFormatFilter(self) -> str:  # noqa: N802
        return self._library_format

    @Property(bool, notify=stateChanged)
    def canConvertChecked(self) -> bool:  # noqa: N802
        return self.library_model.convertibleCheckedCount > 0 and not self.task_controller.busy

    @Property(bool, notify=stateChanged)
    def canConvertPending(self) -> bool:  # noqa: N802
        return bool(self.library_id and self._counts.get(FileStatus.PENDING.value, 0)) and not self.task_controller.busy

    @Property(bool, notify=stateChanged)
    def canPause(self) -> bool:  # noqa: N802
        return self.task_controller.state == TaskState.CONVERTING

    @Property(bool, notify=stateChanged)
    def canResume(self) -> bool:  # noqa: N802
        return self.task_controller.state == TaskState.PAUSED

    @Property(bool, notify=stateChanged)
    def canCancel(self) -> bool:  # noqa: N802
        return self.task_controller.state in {TaskState.SCANNING, TaskState.CONVERTING, TaskState.PAUSED, TaskState.TRANSCODING}

    @Property(int, notify=stateChanged)
    def flacCount(self) -> int:  # noqa: N802
        return len(self._flac_sources)

    @Property(bool, notify=stateChanged)
    def canStartFlac(self) -> bool:  # noqa: N802
        return bool(self._flac_sources) and not self.task_controller.busy

    @Property(bool, notify=stateChanged)
    def allowClose(self) -> bool:  # noqa: N802
        return self._allow_close

    @Slot(str)
    def navigate(self, page_key: str) -> None:
        if page_key not in PAGE_KEYS or page_key == self._current_page:
            return
        self._current_page = page_key
        if page_key == "tasks":
            self.refreshQueue()
        elif page_key == "history":
            self.refreshHistory()
        elif page_key == "language":
            self.refreshLanguage()
        elif page_key == "settings":
            self._sync_ignore_rules()
        self._emit_state()

    def _load_initial_library(self) -> None:
        path = self.settings.music_library_path
        if path and Path(path).is_dir():
            self._activate_library(path, clear_checked=True)
            self.refreshAll()
            self._configure_watcher()
            behavior = self.settings.startup_behavior
            if behavior == "background_incremental":
                QTimer.singleShot(250, lambda: self.startScan("incremental", True))
            elif behavior == "full_rescan":
                QTimer.singleShot(250, lambda: self.startScan("full", False))
        elif path:
            self._task_title = self._tr("top.noLibraryStatus")
            self._task_detail = path
            self.toastRequested.emit(self._tr("toast.fileMissing"), "warning")
            self._emit_state()
        else:
            self.refreshAll()

    def _activate_library(self, path: str, *, clear_checked: bool) -> int:
        normalized = str(Path(path).resolve())
        changed = normalized != self.settings.music_library_path
        self.library_id = self.db.set_selected_library(normalized)
        self.settings.music_library_path = normalized
        self._settings_draft["music_library_path"] = normalized
        if changed or clear_checked:
            self.library_model.clearChecked()
            self.queue_model.clearChecked()
        return self.library_id

    @Slot(str)
    def useLibraryFolder(self, value: str) -> None:  # noqa: N802
        path = _to_local_path(value)
        if not path or not Path(path).is_dir():
            self.toastRequested.emit(self._tr("toast.fileMissing"), "error")
            return
        self._activate_library(path, clear_checked=True)
        self.db.save_settings(self.settings)
        self._settings_dirty = False
        self._configure_watcher()
        self.refreshAll()
        self.startScan("full", False)

    @Slot(str)
    def setLibrarySearch(self, value: str) -> None:  # noqa: N802
        self._library_search = value.strip()
        self.refreshLibrary()

    @Slot(str)
    def setLibraryStatusFilter(self, value: str) -> None:  # noqa: N802
        self._library_status = value if value else "all"
        self.refreshLibrary()

    @Slot(str)
    def setLibraryFormatFilter(self, value: str) -> None:  # noqa: N802
        self._library_format = value if value else "all"
        self.refreshLibrary()

    @Slot()
    def resetLibraryFilters(self) -> None:  # noqa: N802
        self._library_search = ""
        self._library_status = "all"
        self._library_format = "all"
        self.refreshLibrary()

    @Slot()
    def refreshAll(self) -> None:  # noqa: N802
        self.refreshLibrary()
        self.refreshQueue()
        self.refreshHistory()
        self.refreshLanguage()

    @Slot()
    def refreshLibrary(self) -> None:  # noqa: N802
        records: list[FileRecord] = []
        if self.library_id:
            records = self.db.list_files(
                self.library_id,
                search=self._library_search,
                status=self._library_status,
                extension=self._library_format,
            )
            self._counts = self.db.counts_by_status(self.library_id)
        else:
            self._counts = {"all": 0, **{status.value: 0 for status in FileStatus}}
        self.library_model.set_records(records)
        self._emit_state()

    @Slot()
    def refreshQueue(self) -> None:  # noqa: N802
        pending: list[FileRecord] = []
        failed: list[FileRecord] = []
        if self.library_id:
            pending = self.db.list_files(self.library_id, status=FileStatus.PENDING.value)
            failed = self.db.list_files(self.library_id, status=FileStatus.FAILED.value)
        self.queue_model.set_records([*pending, *failed])
        groups: dict[str, list[FileRecord]] = {}
        for record in failed:
            groups.setdefault(_failure_group_key(record.failure_reason), []).append(record)
        self.failure_group_model.set_rows(
            {
                "key": key,
                "title": self._tr(f"failureGroups.{key}"),
                "description": records[0].failure_reason or self._tr("failureGroups.noMessage"),
                "count": len(records),
                "file_ids": [record.id for record in records if record.id is not None],
            }
            for key, records in sorted(groups.items(), key=lambda item: len(item[1]), reverse=True)
        )
        self._emit_state()

    @Slot(str, bool)
    def startScan(self, scan_mode: str = "incremental", skip_unstable: bool = False) -> None:  # noqa: N802
        if scan_mode not in {"incremental", "full"}:
            return
        path = self.settings.music_library_path
        if not path or not Path(path).is_dir():
            self.toastRequested.emit(self._tr("toast.fileMissing"), "warning")
            return
        try:
            self.task_controller.begin_scan()
        except TaskTransitionError:
            self.toastRequested.emit(self._tr("toast.scanAlreadyRunning"), "warning")
            return
        self._task_progress = 0.0
        self._task_title = self._tr("progress.fullRescan" if scan_mode == "full" else "progress.checking")
        self._task_detail = self._tr("progress.fullDetail" if scan_mode == "full" else "progress.checkingDetail")
        self._task_metrics = self._tr("progress.counting")
        self._emit_state()

        thread = QThread(self)
        worker = ScanWorker(self.db.db_path, path, deepcopy(self.settings), scan_mode, skip_unstable)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progressChanged.connect(self._on_scan_progress)
        worker.finished.connect(self._on_scan_finished)
        worker.failed.connect(self._on_scan_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._on_worker_thread_finished)
        self.scan_thread = thread
        self.scan_worker = worker
        thread.start()

    @Slot()
    def requestFullScan(self) -> None:  # noqa: N802
        self._ask_confirmation(
            "full-scan",
            self._tr("dialog.fullRescan.title"),
            self._tr("dialog.fullRescan.body"),
            self._tr("button.fullRescan"),
            True,
            lambda accepted: self.startScan("full", False) if accepted else None,
        )

    @Slot(object)
    def _on_scan_progress(self, progress: ScanProgress) -> None:
        current = Path(progress.current_path).name if progress.current_path else self._tr("progress.scanning")
        self._task_detail = current
        self._task_metrics = self._tr(
            "progress.metricsScan",
            files=progress.files_scanned,
            added=progress.added,
            updated=progress.updated,
            unchanged=progress.unchanged,
            delayed=progress.skipped_unstable,
            pending=progress.pending,
        )
        self._emit_state()

    @Slot(object)
    def _on_scan_finished(self, progress: ScanProgress) -> None:
        self._task_progress = 0.0 if progress.canceled else 100.0
        self._task_title = self._tr("progress.scanCanceled" if progress.canceled else ("progress.fullComplete" if progress.mode == "full" else "progress.upToDate"))
        self._task_detail = self._tr("progress.noChanges") if not progress.canceled and not (progress.added or progress.updated or progress.missing) else self._tr("progress.refreshed")
        self._task_metrics = self._tr(
            "progress.scanMetrics",
            files=progress.files_scanned,
            added=progress.added,
            updated=progress.updated,
            unchanged=progress.unchanged,
            delayed=progress.skipped_unstable,
            missing=progress.missing,
        )
        self.refreshAll()
        self.toastRequested.emit(
            self._tr("toast.scanCanceled") if progress.canceled else self._tr("toast.checkedChanges", added=progress.added, updated=progress.updated, missing=progress.missing),
            "warning" if progress.canceled else "success",
        )

    @Slot(str)
    def _on_scan_failed(self, message: str) -> None:
        self._task_progress = 0.0
        self._task_title = self._tr("dialog.scanFailed.title")
        self._task_detail = message
        self.toastRequested.emit(message, "error")
        self.dialogRequested.emit(self._tr("dialog.scanFailed.title"), message, "error")
        self.refreshAll()

    @Slot()
    def convertPending(self) -> None:  # noqa: N802
        if not self.library_id:
            self.toastRequested.emit(self._tr("nav.chooseFolder"), "info")
            return
        file_ids = [record.id for record in self.db.list_pending_files(self.library_id) if record.id is not None]
        self._start_conversion(file_ids)

    @Slot()
    def convertChecked(self) -> None:  # noqa: N802
        if not self.library_id:
            return
        records = self.db.list_files_by_ids(sorted(self.library_model.checked_ids))
        file_ids = [
            int(record.id)
            for record in records
            if record.id is not None and record.library_id == self.library_id and record.status in CONVERTIBLE_STATUSES
        ]
        self._start_conversion(file_ids)

    @Slot(int)
    def convertRow(self, row: int) -> None:  # noqa: N802
        record = self.library_model.record_at(row)
        if record and record.id is not None and record.status in CONVERTIBLE_STATUSES:
            self._start_conversion([record.id])

    @Slot("QVariantList")
    def retryFileIds(self, values: list[Any]) -> None:  # noqa: N802
        ids = [int(value) for value in (_plain_value(values) or [])]
        if not self.library_id:
            return
        records = self.db.list_files_by_ids(ids)
        retry = [int(record.id) for record in records if record.id is not None and record.library_id == self.library_id and record.status == FileStatus.FAILED.value]
        self._start_conversion(retry)

    @Slot()
    def retryAllFailed(self) -> None:  # noqa: N802
        if not self.library_id:
            return
        self._start_conversion([int(record.id) for record in self.db.list_files(self.library_id, status=FileStatus.FAILED.value) if record.id is not None])

    def _start_conversion(self, file_ids: list[int]) -> None:
        if not file_ids:
            self.toastRequested.emit(self._tr("toast.noPending"), "info")
            return
        if not self.library_id or not self.settings.music_library_path:
            return
        try:
            self.task_controller.begin_conversion()
        except TaskTransitionError:
            self.toastRequested.emit(self._tr("toast.conversionRunning"), "warning")
            return
        self._last_conversion_percent = 0.0
        self._conversion_started_at = time.monotonic()
        self._task_progress = 0.0
        self._task_title = self._tr("progress.startingConversion")
        self._task_detail = self._tr("progress.preparingQueue")
        self._task_metrics = ""
        self._task_summary = {}
        self._emit_state()

        thread = QThread(self)
        worker = ConversionWorker(
            self.db.db_path,
            self.library_id,
            self.settings.music_library_path,
            deepcopy(self.settings),
            file_ids,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progressChanged.connect(self._on_conversion_progress)
        worker.finished.connect(self._on_conversion_finished)
        worker.failed.connect(self._on_conversion_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._on_worker_thread_finished)
        self.conversion_thread = thread
        self.conversion_worker = worker
        thread.start()

    @Slot(object)
    def _on_conversion_progress(self, progress: QueueProgress) -> None:
        total = int(progress.total or 0)
        converted = int(progress.converted or 0)
        skipped = int(progress.skipped or 0)
        failed = int(progress.failed or 0)
        completed = int(progress.completed or converted + skipped + failed)
        remaining = int(progress.remaining if progress.remaining is not None else max(0, total - completed))
        percent = max(self._last_conversion_percent, min(100.0, float(progress.overall_percent or 0)))
        self._last_conversion_percent = percent
        self._task_progress = percent
        self._task_title = self._tr("progress.paused") if progress.paused else self._tr("progress.converting")
        self._task_detail = Path(progress.current_file).name if progress.current_file else self._tr("progress.preparingQueue")
        self._task_metrics = self._tr("progress.metricsQueue", success=converted, failed=failed, skipped=skipped, remaining=remaining)
        self._emit_state()

    @Slot(object)
    def _on_conversion_finished(self, progress: QueueProgress) -> None:
        duration = max(0.0, time.monotonic() - self._conversion_started_at)
        total = int(progress.total or 0)
        converted = int(progress.converted or 0)
        skipped = int(progress.skipped or 0)
        failed = int(progress.failed or 0)
        remaining = int(progress.remaining or progress.not_processed or max(0, total - converted - skipped - failed))
        self._task_progress = max(self._last_conversion_percent, 0.0 if progress.canceled else 100.0)
        self._task_title = self._tr("progress.conversionCanceled" if progress.canceled else "progress.conversionComplete")
        self._task_detail = self._tr("progress.canceledDetail" if progress.canceled else "progress.completeDetail")
        self._task_metrics = self._tr("progress.metricsQueue", success=converted, failed=failed, skipped=skipped, remaining=remaining)
        outputs = [record.output_path for record in self.db.list_files_by_ids(sorted(self.library_model.checked_ids)) if record.output_path]
        output_hint = str(Path(outputs[0]).parent) if outputs else self.settings.custom_output_folder or self.settings.music_library_path
        self._task_summary = {
            "converted": converted,
            "skipped": skipped,
            "failed": failed,
            "remaining": remaining,
            "duration": f"{duration:.1f} s",
            "output": output_hint,
            "canceled": bool(progress.canceled),
        }
        self.library_model.clearChecked()
        self.queue_model.clearChecked()
        self.refreshAll()
        self.toastRequested.emit(self._task_title, "warning" if progress.canceled else ("error" if failed else "success"))

    @Slot(str)
    def _on_conversion_failed(self, message: str) -> None:
        self._task_progress = 0.0
        self._task_title = self._tr("dialog.conversionFailed.title")
        self._task_detail = message
        self.library_model.clearChecked()
        self.queue_model.clearChecked()
        self.refreshAll()
        self.toastRequested.emit(message, "error")
        self.dialogRequested.emit(self._task_title, message, "error")

    @Slot()
    def pauseConversion(self) -> None:  # noqa: N802
        if self.conversion_worker is None:
            return
        try:
            self.task_controller.pause()
        except TaskTransitionError:
            return
        self.conversion_worker.pause()
        self._task_title = self._tr("progress.paused")
        self._emit_state()

    @Slot()
    def resumeConversion(self) -> None:  # noqa: N802
        if self.conversion_worker is None:
            return
        try:
            self.task_controller.resume()
        except TaskTransitionError:
            return
        self.conversion_worker.resume()
        self._task_title = self._tr("progress.converting")
        self._emit_state()

    @Slot()
    def cancelCurrentTask(self) -> None:  # noqa: N802
        if not self.task_controller.request_cancel():
            return
        worker = self.scan_worker or self.conversion_worker or self.flac_worker
        if worker is not None:
            worker.cancel()
        self._task_title = self._tr("progress.canceling")
        self._emit_state()

    @Slot(int, str)
    def performFileAction(self, row: int, action: str) -> None:  # noqa: N802
        if self._current_page == "tasks":
            record = self.queue_model.record_at(row)
        elif self._current_page == "language":
            record = self.language_model.record_at(row)
        else:
            record = self.library_model.record_at(row)
        if record is None:
            return
        if action in {"convert", "retry"} and record.id is not None:
            self._start_conversion([record.id])
        elif action == "ignore" and record.id is not None:
            self.db.mark_ignored([record.id], True)
            self.refreshAll()
        elif action == "restore" and record.id is not None:
            self.db.mark_ignored([record.id], False)
            self.refreshAll()
        elif action == "revealSource":
            self._reveal(record.absolute_path)
        elif action == "revealOutput":
            self._reveal(record.output_path)
        elif action == "openOutput":
            self._open_file(record.output_path)
        elif action == "copySource":
            self._copy_text(record.absolute_path, "toast.copiedPaths")
        elif action == "copyOutput":
            self._copy_text(record.output_path, "toast.copiedOutput")
        elif action == "copyIssue":
            self._copy_text(record.failure_reason, "toast.copiedIssues")

    @Slot(str)
    def performCheckedAction(self, action: str) -> None:  # noqa: N802
        if not self.library_id:
            return
        records = [record for record in self.db.list_files_by_ids(sorted(self.library_model.checked_ids)) if record.library_id == self.library_id]
        if not records:
            return
        if action == "ignore":
            self.db.mark_ignored([int(record.id) for record in records if record.id is not None], True)
            self.library_model.clearChecked()
            self.refreshAll()
        elif action == "copySource":
            self._copy_text("\n".join(record.absolute_path for record in records), "toast.copiedPaths", len(records))
        elif action == "revealSource":
            self._reveal(records[0].absolute_path)

    @Slot(str)
    def setHistorySearch(self, value: str) -> None:  # noqa: N802
        self._history_search = value.strip().casefold()
        self.refreshHistory()

    @Slot(str)
    def setHistoryStatusFilter(self, value: str) -> None:  # noqa: N802
        self._history_status = value or "all"
        self.refreshHistory()

    @Slot()
    def refreshHistory(self) -> None:  # noqa: N802
        rows = list(self.db.list_history(self.library_id)) if self.library_id else []
        filtered = []
        for row in rows:
            if self._history_status != "all" and str(row["status"]) != self._history_status:
                continue
            haystack = f"{row['source_path']} {row['output_path'] or ''} {row['error_message'] or ''}".casefold()
            if self._history_search and self._history_search not in haystack:
                continue
            filtered.append(row)
        self.history_model.set_rows(filtered)
        logs = self.db.list_logs()
        self._logs_text = "\n".join(f"{row['created_at']} [{row['level']}] {row['category']}: {row['message']}" for row in logs)
        self._emit_state()

    @Slot(int, str)
    def performHistoryAction(self, row: int, action: str) -> None:  # noqa: N802
        item = self.history_model.get(row)
        if not item:
            return
        if action == "openOutput":
            self._open_file(item["outputPath"])
        elif action == "revealOutput":
            self._reveal(item["outputPath"])
        elif action == "copySource":
            self._copy_text(item["sourcePath"], "toast.copiedPaths")
        elif action == "copyOutput":
            self._copy_text(item["outputPath"], "toast.copiedOutput")
        elif action == "copyIssue":
            self._copy_text(item["errorMessage"], "toast.copiedIssues")
        elif action == "retry" and int(item["fileId"]) >= 0:
            self._start_conversion([int(item["fileId"])])

    @Slot(str)
    def exportLogs(self, value: str) -> None:  # noqa: N802
        path = Path(_to_local_path(value))
        if not path.name:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self._logs_text, encoding="utf-8")
        except OSError as exc:
            self.toastRequested.emit(str(exc), "error")
            return
        self.toastRequested.emit(self._tr("toast.logsExported", path=str(path)), "success")

    @Slot(str)
    def setLanguageSearch(self, value: str) -> None:  # noqa: N802
        self._language_search = value.strip().casefold()
        self.refreshLanguage()

    @Slot(str)
    def setLanguageFilter(self, value: str) -> None:  # noqa: N802
        self._language_filter = value or "all"
        self.refreshLanguage()

    @Slot()
    def refreshLanguage(self) -> None:  # noqa: N802
        records = self.db.list_files(self.library_id) if self.library_id else []
        rows: list[ClassifiedRow] = []
        for record in records:
            classification = classify_path(record.relative_path)
            if self._language_filter != "all" and classification.language != self._language_filter:
                continue
            language_label = self._tr(f"language.name.{classification.language}")
            haystack = f"{record.relative_path} {record.output_path} {record.failure_reason} {classification.signal} {language_label}".casefold()
            if self._language_search and self._language_search not in haystack:
                continue
            rows.append(ClassifiedRow(record, classification))
        order = {value: index for index, value in enumerate(LANGUAGE_ORDER)}
        rows.sort(key=lambda item: (order.get(item.classification.language, 999), item.record.relative_path.casefold()))
        self.language_model.set_rows(rows)
        self._emit_state()

    @Slot(str, "QVariant")
    def setSetting(self, key: str, value: Any) -> None:  # noqa: N802
        if key not in self._settings_draft:
            return
        value = _plain_value(value)
        if key in {"music_library_path", "custom_output_folder", "flac_mp3_output_folder"}:
            value = _to_local_path(value)
        if key == "max_concurrent_conversions":
            value = max(1, min(16, int(value)))
        elif key == "flac_mp3_bitrate":
            value = int(value)
        elif key == "ignored_folder_rules":
            value = [str(item) for item in value]
        old_theme = self.theme
        old_language = self.language
        self._settings_draft[key] = value
        self._settings_dirty = self._settings_draft != asdict(self.settings)
        if key == "theme" and value != old_theme:
            self.themeChanged.emit()
        if key == "language" and value != old_language:
            self.translator.language = str(value)
            self._i18n_revision += 1
            self.languageChanged.emit()
            self.refreshAll()
        if key == "ignored_folder_rules":
            self._sync_ignore_rules()
        self._emit_state()

    @Slot(str, "QVariant")
    def setFlacOption(self, key: str, value: Any) -> None:  # noqa: N802
        allowed = {
            "flac_mp3_bitrate",
            "flac_mp3_output_location",
            "flac_mp3_output_folder",
            "flac_mp3_preserve_structure",
            "flac_mp3_skip_existing",
        }
        if key not in allowed:
            return
        value = _plain_value(value)
        if key == "flac_mp3_output_folder":
            value = _to_local_path(value)
        elif key == "flac_mp3_bitrate":
            value = int(value)
        setattr(self.settings, key, value)
        self._settings_draft[key] = value
        self.db.save_settings(self.settings)
        self._settings_dirty = self._settings_draft != asdict(self.settings)
        self._refresh_flac_model()

    @Slot()
    def discardSettings(self) -> None:  # noqa: N802
        old_theme = self.theme
        old_language = self.language
        self._settings_draft = asdict(self.settings)
        self._settings_dirty = False
        self.translator.language = self.settings.language
        if self.theme != old_theme:
            self.themeChanged.emit()
        if self.language != old_language:
            self._i18n_revision += 1
            self.languageChanged.emit()
        self._sync_ignore_rules()
        self._emit_state()

    @Slot()
    def saveSettings(self) -> None:  # noqa: N802
        enabling_delete = bool(self._settings_draft.get("delete_source_after_success")) and not self.settings.delete_source_after_success
        if enabling_delete:
            self._ask_confirmation(
                "delete-source-setting",
                self._tr("dialog.deleteSource.title"),
                self._tr("dialog.deleteSource.body"),
                self._tr("dialog.deleteSource.confirm"),
                True,
                lambda accepted: self._commit_settings() if accepted else self._reject_delete_source_setting(),
            )
            return
        self._commit_settings()

    def _reject_delete_source_setting(self) -> None:
        self._settings_draft["delete_source_after_success"] = False
        self._settings_dirty = self._settings_draft != asdict(self.settings)
        self._emit_state()

    def _commit_settings(self) -> None:
        next_settings = AppSettings.from_mapping(deepcopy(self._settings_draft))
        previous_path = self.settings.music_library_path
        self.settings = next_settings
        self._settings_draft = asdict(next_settings)
        self.translator.language = next_settings.language
        self.db.save_settings(next_settings)
        self._settings_dirty = False
        if next_settings.music_library_path and Path(next_settings.music_library_path).is_dir():
            self._activate_library(next_settings.music_library_path, clear_checked=next_settings.music_library_path != previous_path)
        self._configure_watcher()
        self._sync_ignore_rules()
        self.refreshAll()
        self.toastRequested.emit(self._tr("settings.savedNow"), "success")

    @Slot(str)
    def addIgnoreRule(self, value: str) -> None:  # noqa: N802
        rule = value.strip()
        if not rule:
            return
        rules = [str(item) for item in self._settings_draft.get("ignored_folder_rules", [])]
        if rule.casefold() not in {item.casefold() for item in rules}:
            rules.append(rule)
            self.setSetting("ignored_folder_rules", rules)

    @Slot(str)
    def removeIgnoreRule(self, value: str) -> None:  # noqa: N802
        rules = [str(item) for item in self._settings_draft.get("ignored_folder_rules", []) if str(item) != value]
        self.setSetting("ignored_folder_rules", rules)

    @Slot()
    def restoreDefaultIgnoreRules(self) -> None:  # noqa: N802
        self.setSetting("ignored_folder_rules", list(DEFAULT_IGNORED_FOLDERS))

    def _sync_ignore_rules(self) -> None:
        self.ignore_rule_model.set_rows({"value": str(rule), "title": str(rule)} for rule in self._settings_draft.get("ignored_folder_rules", []))

    @Slot("QVariantList")
    def addFlacInputs(self, values: list[Any]) -> None:  # noqa: N802
        paths = [_to_local_path(value) for value in (_plain_value(values) or [])]
        added = 0
        for raw in paths:
            input_path = Path(raw)
            root = input_path if input_path.is_dir() else input_path.parent
            for source_value in discover_flac_files([raw], recursive=True):
                source = Path(source_value).resolve()
                key = os.path.normcase(str(source))
                if key in self._flac_sources:
                    continue
                try:
                    size = source.stat().st_size
                except OSError:
                    size = 0
                self._flac_sources[key] = {
                    "key": key,
                    "source": str(source),
                    "root": str(root.resolve()),
                    "output": "",
                    "completed_output": "",
                    "status": FlacMp3Status.WAITING.value,
                    "size": size,
                    "error": "",
                    "progress": 0.0,
                }
                added += 1
        self._refresh_flac_model()
        if added:
            self.toastRequested.emit(self._tr("flac.added", count=added), "success")
        elif paths:
            self.toastRequested.emit(self._tr("flac.dropNoFiles"), "info")

    @Slot(int)
    def removeFlacRow(self, row: int) -> None:  # noqa: N802
        item = self.flac_model.get(row)
        if item and not self.task_controller.busy:
            self._flac_sources.pop(item["key"], None)
            self._refresh_flac_model()

    @Slot()
    def clearFlac(self) -> None:  # noqa: N802
        if not self.task_controller.busy:
            self._flac_sources.clear()
            self._refresh_flac_model()

    def _flac_output(self, entry: dict[str, Any], *, prefer_completed: bool = True) -> str:
        completed = str(entry.get("completed_output") or "")
        if prefer_completed and completed:
            return completed
        if self.settings.flac_mp3_output_location == "custom_folder" and self.settings.flac_mp3_output_folder:
            return output_path_for(
                entry["source"],
                self.settings.flac_mp3_output_folder,
                relative_root=entry.get("root"),
                preserve_structure=self.settings.flac_mp3_preserve_structure,
            )
        return output_path_for(entry["source"])

    def _refresh_flac_model(self) -> None:
        for entry in self._flac_sources.values():
            entry["output"] = self._flac_output(entry)
        self.flac_model.set_rows(self._flac_sources.values())
        self._emit_state()

    @Slot()
    def startFlacConversion(self) -> None:  # noqa: N802
        if not self._flac_sources:
            self.toastRequested.emit(self._tr("flac.noFiles"), "info")
            return
        if self.settings.flac_mp3_output_location == "custom_folder" and not self.settings.flac_mp3_output_folder:
            self.toastRequested.emit(self._tr("flac.chooseOutput"), "warning")
            return
        try:
            self.task_controller.begin_transcode()
        except TaskTransitionError:
            self.toastRequested.emit(self._tr("flac.otherTaskRunning"), "warning")
            return
        entries = list(self._flac_sources.values())
        jobs = [FlacMp3Job(entry["source"], self._flac_output(entry, prefer_completed=False)) for entry in entries]
        destinations = [os.path.normcase(str(Path(job.output_path).absolute())) for job in jobs]
        if len(destinations) != len(set(destinations)):
            self.task_controller.finish()
            self.toastRequested.emit(self._tr("flac.duplicateOutput"), "error")
            self._emit_state()
            return
        for entry in entries:
            entry["completed_output"] = ""
            entry["status"] = FlacMp3Status.WAITING.value
            entry["error"] = ""
            entry["progress"] = 0.0
        self._refresh_flac_model()
        self._task_progress = 0.0
        self._task_title = self._tr("flac.starting")
        self._task_detail = self._tr("flac.preparing")
        self._task_metrics = ""
        self._emit_state()

        options = FlacMp3Options(
            bitrate_kbps=self.settings.flac_mp3_bitrate,
            overwrite=not self.settings.flac_mp3_skip_existing,
        )
        thread = QThread(self)
        worker = FlacMp3Worker(jobs, options)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progressChanged.connect(self._on_flac_progress)
        worker.finished.connect(self._on_flac_finished)
        worker.failed.connect(self._on_flac_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._on_worker_thread_finished)
        self.flac_thread = thread
        self.flac_worker = worker
        thread.start()

    @Slot(object)
    def _on_flac_progress(self, progress: FlacMp3Progress) -> None:
        self._task_progress = float(progress.overall_percent or 0)
        self._task_title = self._tr("flac.progressTitle")
        self._task_detail = Path(progress.current_file).name if progress.current_file else self._tr("flac.preparing")
        remaining = max(0, progress.total - progress.completed)
        self._task_metrics = self._tr("flac.metrics", converted=progress.converted, skipped=progress.skipped, failed=progress.failed, remaining=remaining)
        by_source = {os.path.normcase(entry["source"]): entry for entry in self._flac_sources.values()}
        for result in progress.results:
            entry = by_source.get(os.path.normcase(result.source_path))
            if entry is None:
                continue
            entry["status"] = result.status.value
            entry["error"] = result.error
            if result.status in {FlacMp3Status.CONVERTED, FlacMp3Status.SKIPPED}:
                entry["completed_output"] = result.output_path
            entry["progress"] = 100.0
        current = by_source.get(os.path.normcase(progress.current_file)) if progress.current_file else None
        if current is not None and current["status"] == FlacMp3Status.WAITING.value:
            current["status"] = FlacMp3Status.CONVERTING.value
            current["progress"] = progress.current_percent
        self._refresh_flac_model()

    @Slot(object)
    def _on_flac_finished(self, progress: FlacMp3Progress) -> None:
        self._on_flac_progress(progress)
        self._task_title = self._tr("flac.canceled" if progress.canceled else "flac.finished")
        self._task_detail = self._tr("flac.cancelingDetail" if progress.canceled else "flac.finishedDetail")
        self._task_progress = float(progress.overall_percent or 0)
        self.toastRequested.emit(self._task_title, "warning" if progress.canceled else ("error" if progress.failed else "success"))
        self._emit_state()

    @Slot(str)
    def _on_flac_failed(self, message: str) -> None:
        self._task_title = self._tr("flac.failed")
        self._task_detail = message
        self.toastRequested.emit(message, "error")
        self.dialogRequested.emit(self._task_title, message, "error")
        self._emit_state()

    @Slot(int, str)
    def performFlacAction(self, row: int, action: str) -> None:  # noqa: N802
        item = self.flac_model.get(row)
        if not item:
            return
        if action == "remove":
            self.removeFlacRow(row)
        elif action == "revealOutput":
            self._reveal(item["outputPath"])
        elif action == "openOutput":
            self._open_file(item["outputPath"])
        elif action == "copyOutput":
            self._copy_text(item["outputPath"], "toast.copiedOutput")
        elif action == "copySource":
            self._copy_text(item["sourcePath"], "toast.copiedPaths")

    def _ask_confirmation(
        self,
        base_token: str,
        title: str,
        body: str,
        accept_label: str,
        danger: bool,
        callback: Callable[[bool], None],
    ) -> str:
        self._confirmation_serial += 1
        token = f"{base_token}:{self._confirmation_serial}"
        self._confirmations[token] = callback
        self.confirmationRequested.emit(token, title, body, accept_label, danger)
        return token

    @Slot(str, bool)
    def respondToConfirmation(self, token: str, accepted: bool) -> None:  # noqa: N802
        callback = self._confirmations.pop(token, None)
        if callback is not None:
            callback(bool(accepted))

    @Slot(result=bool)
    def requestClose(self) -> bool:  # noqa: N802
        if self._allow_close:
            return True
        waiting = self.task_controller.request_close()
        self._close_waiting = waiting
        self._configure_watcher(clear_only=True)
        if not waiting:
            self._allow_close = True
            return True
        for worker in (self.scan_worker, self.conversion_worker, self.flac_worker):
            if worker is not None:
                worker.cancel()
        self._task_title = self._tr("progress.canceling")
        self._emit_state()
        return False

    @Slot()
    def _on_worker_thread_finished(self) -> None:
        sender = self.sender()
        if sender is self.scan_thread:
            self.scan_thread = None
            self.scan_worker = None
        elif sender is self.conversion_thread:
            self.conversion_thread = None
            self.conversion_worker = None
        elif sender is self.flac_thread:
            self.flac_thread = None
            self.flac_worker = None
        due = self.task_controller.finish()
        self._emit_state()
        if self._close_waiting and not any((self.scan_thread, self.conversion_thread, self.flac_thread)):
            self._allow_close = True
            self._close_waiting = False
            self.readyToClose.emit()
        elif due:
            QTimer.singleShot(300, lambda: self.startScan("incremental", True))

    def _configure_watcher(self, *, clear_only: bool = False) -> None:
        existing = self._watcher.directories()
        if existing:
            self._watcher.removePaths(existing)
        if clear_only or not self.settings.enable_folder_watching:
            return
        root = Path(self.settings.music_library_path)
        if not root.is_dir():
            return
        paths: list[str] = []
        try:
            for current, directories, _files in os.walk(root):
                directories[:] = [name for name in directories if not should_ignore_dir(Path(current) / name, self.settings.ignored_folder_rules)]
                paths.append(str(Path(current)))
                if len(paths) >= 512:
                    self.toastRequested.emit(self._tr("toast.watchLimit"), "warning")
                    break
        except OSError:
            self.toastRequested.emit(self._tr("toast.watchEnumerate"), "warning")
        if paths:
            rejected = self._watcher.addPaths(paths)
            if rejected:
                self.toastRequested.emit(self._tr("toast.watchPartial"), "warning")

    @Slot(str)
    def _on_watched_directory_changed(self, _path: str) -> None:
        if self.task_controller.defer_watch_scan():
            self.toastRequested.emit(self._tr("toast.folderChanged"), "info")
            self._watch_rescan_timer.start()

    def _copy_text(self, text: str, translation_key: str, count: int = 1) -> None:
        if not text:
            return
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)
        self.toastRequested.emit(self._tr(translation_key, count=count), "success")

    def _reveal(self, path: str) -> None:
        if not path:
            self.toastRequested.emit(self._tr("toast.noOutput"), "warning")
            return
        result = reveal_in_file_manager(path)
        if result.status == FileManagerStatus.FALLBACK_OPENED:
            self.toastRequested.emit(self._tr("toast.revealFallback"), "warning")
        elif not result.ok:
            self.toastRequested.emit(self._tr("toast.revealFailed"), "error")

    def _open_file(self, path: str) -> None:
        if not path or not Path(path).is_file() or not QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
            self.toastRequested.emit(self._tr("toast.openOutputFailed"), "error")

    @Slot()
    def openSummaryOutput(self) -> None:  # noqa: N802
        path = str(self._task_summary.get("output") or self.settings.custom_output_folder or self.settings.music_library_path)
        result = open_folder(path)
        if not result.ok:
            self.toastRequested.emit(self._tr("toast.openFailed"), "error")


__all__ = ["ApplicationBridge", "PAGE_KEYS"]
