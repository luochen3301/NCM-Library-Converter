from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Callable

from .core import is_valid_audio_output
from .library_db import LibraryDB, utc_now
from .models import (
    AUDIO_EXTENSIONS,
    AppSettings,
    FileRecord,
    FileStatus,
    NCM_EXTENSION,
    NORMAL_AUDIO_EXTENSIONS,
    ScanProgress,
    candidate_output_paths,
    compute_fingerprint,
    normalize_relative_path,
)


ProgressCallback = Callable[[ScanProgress], None]


def should_ignore_dir(path: Path, ignored_rules: list[str]) -> bool:
    name = path.name.lower()
    normalized_rules = {rule.strip().lower() for rule in ignored_rules if rule.strip()}
    if name in normalized_rules:
        return True
    if name.startswith(".") and name not in {".", ".."}:
        return True
    try:
        if path.is_symlink():
            return True
    except OSError:
        return True
    return False


def _emit(progress_callback: ProgressCallback | None, progress: ScanProgress) -> None:
    if progress_callback:
        progress_callback(progress)


def scan_library(
    db: LibraryDB,
    library_path: str,
    settings: AppSettings,
    cancel_event: threading.Event | None = None,
    progress_callback: ProgressCallback | None = None,
    scan_mode: str = "incremental",
    skip_unstable: bool = False,
) -> ScanProgress:
    if scan_mode not in {"incremental", "full"}:
        raise ValueError(f"Unsupported scan mode: {scan_mode}")

    root = Path(library_path)
    if not root.exists():
        raise FileNotFoundError(f"Music library folder does not exist: {library_path}")
    if not root.is_dir():
        raise NotADirectoryError(f"Music library path is not a folder: {library_path}")

    library_id = db.set_selected_library(str(root))
    existing_records = db.files_by_relative_path(library_id)

    scan_started_at = utc_now()
    progress = ScanProgress(mode=scan_mode)
    seen_relative_paths: set[str] = set()
    snapshot_records: list[FileRecord] = []
    db.add_log("INFO", "scan", f"Started {scan_mode} scanning {root}")

    def handle_file(file_path: Path) -> None:
        nonlocal progress
        if cancel_event and cancel_event.is_set():
            progress.canceled = True
            return
        progress.files_scanned += 1
        progress.current_path = str(file_path)
        extension = file_path.suffix.lower()
        if extension not in AUDIO_EXTENSIONS:
            _emit(progress_callback, progress)
            return

        if extension == NCM_EXTENSION:
            progress.ncm_found += 1

        try:
            relative_path = normalize_relative_path(file_path.relative_to(root))
            seen_relative_paths.add(relative_path)
            stat = file_path.stat()
            file_size = stat.st_size
            modified_time = stat.st_mtime_ns
            if skip_unstable and _looks_unstable(modified_time):
                progress.skipped_unstable += 1
                _emit(progress_callback, progress)
                return

            existing = existing_records.get(relative_path)
            if existing and existing.file_size == file_size and existing.modified_time == modified_time:
                status, output_path, failure_reason = _status_for_unchanged_file(
                    file_path=file_path,
                    root=root,
                    settings=settings,
                    extension=extension,
                    existing=existing,
                )
                ignored = bool(existing.ignored)
                if ignored:
                    status = FileStatus.IGNORED.value
                    output_path = existing.output_path
                    failure_reason = existing.failure_reason

                if (
                    existing.status != status
                    or existing.output_path != output_path
                    or existing.failure_reason != failure_reason
                    or existing.absolute_path != str(file_path)
                    or existing.extension != extension
                    or existing.source_deleted
                ):
                    record = FileRecord(
                        id=existing.id,
                        library_id=library_id,
                        relative_path=relative_path,
                        absolute_path=str(file_path),
                        file_size=file_size,
                        modified_time=modified_time,
                        fingerprint=existing.fingerprint,
                        strict_hash=existing.strict_hash,
                        extension=extension,
                        status=status,
                        output_path=output_path,
                        failure_reason=failure_reason,
                        last_scan_at=scan_started_at,
                        last_seen_at=scan_started_at,
                        ignored=ignored,
                        source_deleted=False,
                    )
                    snapshot_records.append(record)
                    progress.updated += 1
                else:
                    progress.unchanged += 1
                _increment_progress_status(progress, status)
                _emit(progress_callback, progress)
                return

            file_size, modified_time, fingerprint, strict_hash = compute_fingerprint(
                file_path,
                relative_path,
                strict=settings.strict_verification,
            )
            status = _detect_status(
                file_path=file_path,
                root=root,
                settings=settings,
                extension=extension,
                fingerprint=fingerprint,
                existing=existing,
            )
            output_path = _detect_output_path(file_path, root, settings, existing)
            failure_reason = existing.failure_reason if existing and status == FileStatus.FAILED.value else ""
            ignored = bool(existing.ignored) if existing else False
            if ignored:
                status = FileStatus.IGNORED.value

            record = FileRecord(
                id=existing.id if existing else None,
                library_id=library_id,
                relative_path=relative_path,
                absolute_path=str(file_path),
                file_size=file_size,
                modified_time=modified_time,
                fingerprint=fingerprint,
                strict_hash=strict_hash,
                extension=extension,
                status=status,
                output_path=output_path,
                failure_reason=failure_reason,
                last_scan_at=scan_started_at,
                last_seen_at=scan_started_at,
                ignored=ignored,
                source_deleted=False,
            )
            snapshot_records.append(record)
            if existing:
                progress.updated += 1
            else:
                progress.added += 1
            _increment_progress_status(progress, status)
        except OSError as exc:
            db.add_log("ERROR", "scan", f"Could not scan {file_path}: {exc}")
            raise
        _emit(progress_callback, progress)

    try:
        if settings.recursive_scan:
            def raise_walk_error(error: OSError) -> None:
                raise error

            for current_root, dirs, files in os.walk(root, onerror=raise_walk_error):
                if cancel_event and cancel_event.is_set():
                    progress.canceled = True
                    break
                dirs[:] = [
                    directory
                    for directory in dirs
                    if not should_ignore_dir(Path(current_root) / directory, settings.ignored_folder_rules)
                ]
                for filename in files:
                    handle_file(Path(current_root) / filename)
                    if progress.canceled:
                        break
                if progress.canceled:
                    break
        else:
            with os.scandir(root) as entries:
                for entry in entries:
                    if cancel_event and cancel_event.is_set():
                        progress.canceled = True
                        break
                    if entry.is_file():
                        handle_file(Path(entry.path))
    except BaseException as exc:
        db.add_log("ERROR", "scan", f"Aborted {scan_mode} scanning {root}: {exc}")
        raise

    if cancel_event and cancel_event.is_set():
        progress.canceled = True
    if progress.canceled:
        db.add_log("WARNING", "scan", f"Canceled {scan_mode} scanning {root}")
        _emit(progress_callback, progress)
        return progress

    try:
        committed = db.commit_scan_snapshot(
            library_id,
            snapshot_records,
            seen_relative_paths,
            scan_started_at,
            scan_mode,
        )
    except BaseException as exc:
        db.add_log("ERROR", "scan", f"Could not commit {scan_mode} scan for {root}: {exc}")
        raise
    progress.missing += committed.missing
    duplicates = db.duplicate_warnings(library_id)
    if duplicates:
        db.add_log("WARNING", "scan", f"Possible duplicate files detected: {len(duplicates)} groups")
    db.add_log("INFO", "scan", f"Finished {scan_mode} scanning {root}")
    _emit(progress_callback, progress)
    return progress


def _looks_unstable(modified_time_ns: int, settle_seconds: float = 2.5) -> bool:
    return time.time_ns() - modified_time_ns < int(settle_seconds * 1_000_000_000)


def _status_for_unchanged_file(
    file_path: Path,
    root: Path,
    settings: AppSettings,
    extension: str,
    existing: FileRecord,
) -> tuple[str, str, str]:
    if existing.ignored:
        return FileStatus.IGNORED.value, existing.output_path, existing.failure_reason
    if extension in NORMAL_AUDIO_EXTENSIONS:
        return FileStatus.NORMAL.value, existing.output_path, ""
    if extension != NCM_EXTENSION:
        return FileStatus.UNKNOWN.value, existing.output_path, existing.failure_reason

    output_path = _detect_output_path(file_path, root, settings, existing)
    if output_path:
        return FileStatus.CONVERTED.value, output_path, ""
    if existing.status == FileStatus.FAILED.value:
        return FileStatus.FAILED.value, "", existing.failure_reason
    return FileStatus.PENDING.value, "", ""


def _detect_status(
    file_path: Path,
    root: Path,
    settings: AppSettings,
    extension: str,
    fingerprint: str,
    existing: FileRecord | None,
) -> str:
    if existing and existing.ignored:
        return FileStatus.IGNORED.value
    if extension in NORMAL_AUDIO_EXTENSIONS:
        return FileStatus.NORMAL.value
    if extension != NCM_EXTENSION:
        return FileStatus.UNKNOWN.value

    source_changed = bool(existing and existing.fingerprint != fingerprint)
    if existing and existing.status == FileStatus.FAILED.value and not source_changed:
        return FileStatus.FAILED.value

    if _detect_output_path(file_path, root, settings, existing):
        return FileStatus.CONVERTED.value

    return FileStatus.PENDING.value


def _detect_output_path(
    file_path: Path,
    root: Path,
    settings: AppSettings,
    existing: FileRecord | None,
) -> str:
    known_output_path = existing.output_path if existing else ""
    for candidate in candidate_output_paths(file_path, root, settings, known_output_path):
        if is_valid_audio_output(candidate):
            return candidate
    return ""


def _increment_progress_status(progress: ScanProgress, status: str) -> None:
    if status == FileStatus.PENDING.value:
        progress.pending += 1
    elif status == FileStatus.CONVERTED.value:
        progress.converted += 1
    elif status == FileStatus.NORMAL.value:
        progress.normal += 1
    elif status == FileStatus.FAILED.value:
        progress.failed += 1
    elif status == FileStatus.MISSING.value:
        progress.missing += 1
    elif status == FileStatus.IGNORED.value:
        progress.ignored += 1
