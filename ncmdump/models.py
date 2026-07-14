from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable


class FileStatus(str, Enum):
    PENDING = "pending"
    CONVERTED = "converted"
    NORMAL = "normal"
    FAILED = "failed"
    MISSING = "missing"
    IGNORED = "ignored"
    UNKNOWN = "unknown"


class TaskState(str, Enum):
    IDLE = "idle"
    SCANNING = "scanning"
    CONVERTING = "converting"
    TRANSCODING = "transcoding"
    PAUSED = "paused"
    CANCELING = "canceling"
    CLOSING = "closing"


NORMAL_AUDIO_EXTENSIONS = {".flac", ".mp3", ".wav", ".m4a", ".aac", ".ogg"}
NCM_EXTENSION = ".ncm"
AUDIO_EXTENSIONS = NORMAL_AUDIO_EXTENSIONS | {NCM_EXTENSION}
DEFAULT_IGNORED_FOLDERS = [
    "node_modules",
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".cache",
    "cache",
    "caches",
    "tmp",
    "temp",
    "$recycle.bin",
    "system volume information",
]


@dataclass
class AppSettings:
    music_library_path: str = ""
    output_format: str = "flac"
    output_location: str = "same_folder"
    custom_output_folder: str = ""
    preserve_folder_structure: bool = True
    delete_source_after_success: bool = False
    skip_existing_output: bool = True
    recursive_scan: bool = True
    auto_scan_on_startup: bool = True
    startup_behavior: str = "background_incremental"
    enable_folder_watching: bool = False
    max_concurrent_conversions: int = 2
    strict_verification: bool = False
    ignored_folder_rules: list[str] = field(default_factory=lambda: list(DEFAULT_IGNORED_FOLDERS))
    theme: str = "dark"
    density: str = "comfortable"
    language: str = "system"
    flac_mp3_bitrate: int = 320
    flac_mp3_output_location: str = "same_folder"
    flac_mp3_output_folder: str = ""
    flac_mp3_preserve_structure: bool = True
    flac_mp3_skip_existing: bool = True

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> "AppSettings":
        settings = cls()
        if not data:
            return settings
        had_startup_behavior = "startup_behavior" in data
        for key, value in data.items():
            if hasattr(settings, key):
                setattr(settings, key, value)
        if not had_startup_behavior:
            settings.startup_behavior = "background_incremental" if settings.auto_scan_on_startup else "cache_only"
        if settings.startup_behavior not in {"cache_only", "background_incremental", "full_rescan"}:
            settings.startup_behavior = "background_incremental"
        settings.auto_scan_on_startup = settings.startup_behavior != "cache_only"
        try:
            settings.max_concurrent_conversions = max(1, int(settings.max_concurrent_conversions))
        except (TypeError, ValueError):
            settings.max_concurrent_conversions = 2
        if not isinstance(settings.ignored_folder_rules, list):
            settings.ignored_folder_rules = list(DEFAULT_IGNORED_FOLDERS)
        if settings.density not in {"comfortable", "compact"}:
            settings.density = "comfortable"
        if settings.language not in {"system", "en", "zh_CN"}:
            settings.language = "system"
        if settings.theme in {"obsidian", "dark"}:
            settings.theme = "dark"
        elif settings.theme != "light":
            settings.theme = "dark"
        try:
            settings.flac_mp3_bitrate = int(settings.flac_mp3_bitrate)
        except (TypeError, ValueError):
            settings.flac_mp3_bitrate = 320
        if settings.flac_mp3_bitrate not in {128, 192, 256, 320}:
            settings.flac_mp3_bitrate = 320
        if settings.flac_mp3_output_location not in {"same_folder", "custom_folder"}:
            settings.flac_mp3_output_location = "same_folder"
        return settings

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


@dataclass
class FileRecord:
    id: int | None
    library_id: int
    relative_path: str
    absolute_path: str
    file_size: int
    modified_time: int
    fingerprint: str
    strict_hash: str | None
    extension: str
    status: str
    output_path: str = ""
    failure_reason: str = ""
    last_scan_at: str = ""
    last_seen_at: str = ""
    ignored: bool = False
    source_deleted: bool = False

    @classmethod
    def from_row(cls, row: Any) -> "FileRecord":
        return cls(
            id=row["id"],
            library_id=row["library_id"],
            relative_path=row["relative_path"],
            absolute_path=row["absolute_path"],
            file_size=row["file_size"],
            modified_time=row["modified_time"],
            fingerprint=row["fingerprint"],
            strict_hash=row["strict_hash"],
            extension=row["extension"],
            status=row["status"],
            output_path=row["output_path"] or "",
            failure_reason=row["failure_reason"] or "",
            last_scan_at=row["last_scan_at"] or "",
            last_seen_at=row["last_seen_at"] or "",
            ignored=bool(row["ignored"]),
            source_deleted=bool(row["source_deleted"]) if "source_deleted" in row.keys() else False,
        )


@dataclass
class ScanProgress:
    files_scanned: int = 0
    ncm_found: int = 0
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped_unstable: int = 0
    pending: int = 0
    converted: int = 0
    normal: int = 0
    failed: int = 0
    missing: int = 0
    ignored: int = 0
    current_path: str = ""
    canceled: bool = False
    mode: str = "incremental"


@dataclass
class ActiveConversion:
    file_id: int | None = None
    relative_path: str = ""
    written: int = 0
    total: int = 0
    percent: float = 0.0
    status: str = "converting"


@dataclass(init=False)
class QueueProgress:
    sequence: int = 0
    total: int = 0
    current_file: str = ""
    current_index: int = 0
    state: TaskState = TaskState.IDLE
    completed: int = 0
    converted: int = 0
    skipped: int = 0
    failed: int = 0
    not_processed: int = 0
    remaining: int = 0
    overall_percent: float = 0.0
    active_items: list[ActiveConversion] = field(default_factory=list)
    paused: bool = False
    canceled: bool = False
    message: str = ""

    def __init__(
        self,
        total: int = 0,
        current_file: str = "",
        current_index: int = 0,
        success: int | None = None,
        failed: int = 0,
        remaining: int = 0,
        paused: bool = False,
        canceled: bool = False,
        message: str = "",
        *,
        sequence: int = 0,
        state: TaskState | str = TaskState.IDLE,
        completed: int = 0,
        converted: int = 0,
        skipped: int = 0,
        not_processed: int = 0,
        overall_percent: float = 0.0,
        active_items: list[ActiveConversion] | None = None,
    ) -> None:
        self.sequence = int(sequence)
        self.total = int(total)
        self.current_file = current_file
        self.current_index = int(current_index)
        self.state = TaskState(state)
        self.completed = int(completed)
        self.converted = int(converted if success is None else success)
        self.skipped = int(skipped)
        self.failed = int(failed)
        self.not_processed = int(not_processed)
        self.remaining = int(remaining)
        self.overall_percent = float(overall_percent)
        self.active_items = list(active_items or [])
        self.paused = bool(paused)
        self.canceled = bool(canceled)
        self.message = message

    @property
    def success(self) -> int:
        """Compatibility alias for the pre-V3 successful-conversion counter."""

        return self.converted

    @success.setter
    def success(self, value: int) -> None:
        self.converted = int(value)


def normalize_relative_path(path: str | os.PathLike[str]) -> str:
    return Path(path).as_posix()


def compute_fingerprint(
    file_path: str | os.PathLike[str],
    relative_path: str,
    strict: bool = False,
) -> tuple[int, int, str, str | None]:
    path = Path(file_path)
    stat = path.stat()
    normalized = normalize_relative_path(relative_path)
    fast = f"fast:{normalized}:{stat.st_size}:{stat.st_mtime_ns}"
    strict_hash = sha256_file(path) if strict else None
    fingerprint = f"sha256:{strict_hash}" if strict_hash else fast
    return stat.st_size, stat.st_mtime_ns, fingerprint, strict_hash


def sha256_file(path: str | os.PathLike[str], block_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(block_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def is_reasonable_output(path: str | os.PathLike[str]) -> bool:
    try:
        return Path(path).is_file() and Path(path).stat().st_size > 0
    except OSError:
        return False


def candidate_output_paths(
    source_path: str | os.PathLike[str],
    library_path: str | os.PathLike[str],
    settings: AppSettings,
    known_output_path: str = "",
) -> list[str]:
    source = Path(source_path)
    library = Path(library_path)
    candidates: list[Path] = []
    if known_output_path:
        candidates.append(Path(known_output_path))

    same_folder_base = source.with_suffix("")
    for extension in (".flac", ".mp3"):
        candidates.append(same_folder_base.with_suffix(extension))

    if settings.output_location == "custom_folder" and settings.custom_output_folder:
        try:
            relative_parent = source.parent.relative_to(library)
        except ValueError:
            relative_parent = Path()
        custom_base = Path(settings.custom_output_folder)
        if settings.preserve_folder_structure:
            custom_base = custom_base / relative_parent
        for extension in (".flac", ".mp3"):
            candidates.append((custom_base / source.stem).with_suffix(extension))

    seen = set()
    result = []
    for candidate in candidates:
        value = str(candidate)
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


def make_output_path_factory(
    source_path: str | os.PathLike[str],
    library_path: str | os.PathLike[str],
    settings: AppSettings,
) -> Callable[[str, dict[str, Any]], str]:
    source = Path(source_path)
    library = Path(library_path)

    def _output_path(_: str, meta: dict[str, Any]) -> str:
        extension = str(meta.get("format") or settings.output_format or "flac").lower().lstrip(".")
        if settings.output_location == "custom_folder" and settings.custom_output_folder:
            base = Path(settings.custom_output_folder)
            if settings.preserve_folder_structure:
                try:
                    base = base / source.parent.relative_to(library)
                except ValueError:
                    pass
            base.mkdir(parents=True, exist_ok=True)
            return str((base / source.stem).with_suffix(f".{extension}"))
        return str(source.with_suffix(f".{extension}"))

    return _output_path


def friendly_error_message(error: BaseException | str) -> str:
    text = str(error)
    lowered = text.lower()
    if "no such file" in lowered or "cannot find" in lowered or "not found" in lowered:
        return "File does not exist or was moved."
    if "permission" in lowered or "access is denied" in lowered:
        return "No permission to read the source or write the output file."
    if "disk" in lowered and ("space" in lowered or "full" in lowered):
        return "Not enough disk space for the output file."
    if "being used" in lowered or "in use" in lowered:
        return "The file is currently in use by another application."
    if "file name" in lowered or "filename" in lowered:
        return "The output file name is invalid."
    if "path too long" in lowered:
        return "The file path is too long for this system."
    if "output" in lowered and "folder" in lowered:
        return "The output folder is unavailable."
    if not text:
        return "Conversion failed."
    return text
