from __future__ import annotations

import os
import threading
import time
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Iterable, Sequence

import lameenc
import numpy as np
import soundfile as sf
from mutagen import MutagenError
from mutagen.flac import FLAC
from mutagen.id3 import (
    APIC,
    COMM,
    ID3,
    ID3NoHeaderError,
    TALB,
    TCOM,
    TCON,
    TDRC,
    TIT2,
    TPE1,
    TPE2,
    TPOS,
    TRCK,
)
from mutagen.mp3 import MP3


class FlacMp3Status(str, Enum):
    WAITING = "waiting"
    CONVERTING = "converting"
    CONVERTED = "converted"
    SKIPPED = "skipped"
    FAILED = "failed"
    CANCELED = "canceled"
    NOT_PROCESSED = "not_processed"


class TranscodeCanceled(RuntimeError):
    """Raised internally when a FLAC to MP3 job is canceled."""


@dataclass(frozen=True)
class FlacMp3Options:
    bitrate_kbps: int = 320
    overwrite: bool = False
    quality: int = 2
    block_frames: int = 65_536

    def normalized(self) -> "FlacMp3Options":
        bitrate = int(self.bitrate_kbps)
        if bitrate not in {128, 192, 256, 320}:
            raise ValueError(f"Unsupported MP3 bitrate: {bitrate} kbps")
        quality = min(max(int(self.quality), 0), 9)
        block_frames = max(4_096, int(self.block_frames))
        return FlacMp3Options(bitrate, bool(self.overwrite), quality, block_frames)


@dataclass(frozen=True)
class FlacMp3Job:
    source_path: str
    output_path: str


@dataclass
class FlacMp3Result:
    source_path: str
    output_path: str
    status: FlacMp3Status
    error: str = ""


@dataclass
class FlacMp3Progress:
    sequence: int = 0
    total: int = 0
    completed: int = 0
    converted: int = 0
    skipped: int = 0
    failed: int = 0
    canceled_count: int = 0
    not_processed: int = 0
    canceled: bool = False
    overall_percent: float = 0.0
    current_file: str = ""
    current_percent: float = 0.0
    current_status: FlacMp3Status = FlacMp3Status.WAITING
    results: list[FlacMp3Result] = field(default_factory=list)


ProgressCallback = Callable[[FlacMp3Progress], None]
FileProgressCallback = Callable[[float], None]
CancelCheck = Callable[[], bool]


def discover_flac_files(inputs: Iterable[str | os.PathLike[str]], recursive: bool = True) -> list[str]:
    """Return a stable, duplicate-free list of FLAC files from files and folders."""

    found: dict[str, str] = {}
    for raw_path in inputs:
        path = Path(raw_path).expanduser()
        candidates: Iterable[Path]
        if path.is_file():
            candidates = (path,)
        elif path.is_dir():
            candidates = path.rglob("*") if recursive else path.glob("*")
        else:
            continue
        for candidate in candidates:
            try:
                if not candidate.is_file() or candidate.suffix.casefold() != ".flac":
                    continue
                resolved = str(candidate.resolve())
            except OSError:
                continue
            key = os.path.normcase(resolved)
            found.setdefault(key, resolved)
    return sorted(found.values(), key=lambda value: value.casefold())


def output_path_for(
    source_path: str | os.PathLike[str],
    output_folder: str | os.PathLike[str] | None = None,
    *,
    relative_root: str | os.PathLike[str] | None = None,
    preserve_structure: bool = True,
) -> str:
    source = Path(source_path)
    if output_folder is None:
        return str(source.with_suffix(".mp3"))

    destination_root = Path(output_folder)
    relative_parent = Path()
    if preserve_structure and relative_root is not None:
        try:
            relative_parent = source.parent.resolve().relative_to(Path(relative_root).resolve())
        except (OSError, ValueError):
            relative_parent = Path()
    return str(destination_root / relative_parent / f"{source.stem}.mp3")


def is_valid_mp3(path: str | os.PathLike[str]) -> bool:
    candidate = Path(path)
    try:
        if not candidate.is_file() or candidate.stat().st_size <= 0:
            return False
        audio = MP3(candidate)
        return bool(audio.info and audio.info.length > 0 and audio.info.bitrate > 0)
    except (OSError, ValueError, MutagenError):
        return False


def _output_sample_rate(input_rate: int) -> int:
    supported = (8_000, 11_025, 12_000, 16_000, 22_050, 24_000, 32_000, 44_100, 48_000)
    if input_rate in supported:
        return input_rate
    ceiling = min(max(int(input_rate), supported[0]), supported[-1])
    return min(supported, key=lambda value: abs(value - ceiling))


def _pcm_for_mp3(block: np.ndarray) -> tuple[np.ndarray, int]:
    if block.ndim != 2 or block.shape[1] < 1:
        raise ValueError("The FLAC file does not contain a usable audio channel.")
    channels = int(block.shape[1])
    if channels <= 2:
        return np.ascontiguousarray(block.astype("<i2", copy=False)), channels

    # MP3 supports mono or stereo. Downmix uncommon multichannel FLAC files in
    # a bounded accumulator to avoid int16 overflow, then clip once at output.
    samples = block.astype(np.float32)
    left = samples[:, 0]
    right = samples[:, 1]
    if channels > 2:
        center = samples[:, 2] * np.float32(0.7071)
        left = left + center
        right = right + center
    if channels > 3:
        low_frequency = samples[:, 3] * np.float32(0.25)
        left = left + low_frequency
        right = right + low_frequency
    if channels > 4:
        left = left + samples[:, 4] * np.float32(0.7071)
    if channels > 5:
        right = right + samples[:, 5] * np.float32(0.7071)
    if channels > 6:
        remainder = samples[:, 6:].mean(axis=1) * np.float32(0.5)
        left = left + remainder
        right = right + remainder
    stereo = np.column_stack((left, right))
    peak = float(np.max(np.abs(stereo))) if stereo.size else 0.0
    if peak > 32767.0:
        stereo *= np.float32(32767.0 / peak)
    return np.ascontiguousarray(np.clip(stereo, -32768, 32767).astype("<i2")), 2


def _first_tag(source: FLAC, key: str) -> str:
    values = source.get(key, [])
    return str(values[0]) if values else ""


def _copy_flac_metadata(source_path: Path, output_path: Path) -> None:
    source = FLAC(source_path)
    try:
        tags = ID3(output_path)
    except ID3NoHeaderError:
        tags = ID3()

    text_frames = (
        ("title", "TIT2", TIT2),
        ("artist", "TPE1", TPE1),
        ("album", "TALB", TALB),
        ("albumartist", "TPE2", TPE2),
        ("date", "TDRC", TDRC),
        ("tracknumber", "TRCK", TRCK),
        ("discnumber", "TPOS", TPOS),
        ("genre", "TCON", TCON),
        ("composer", "TCOM", TCOM),
    )
    for key, frame_id, frame_type in text_frames:
        value = _first_tag(source, key)
        if value:
            tags.delall(frame_id)
            tags.add(frame_type(encoding=3, text=[value]))

    comment = _first_tag(source, "comment") or _first_tag(source, "description")
    if comment:
        tags.delall("COMM")
        tags.add(COMM(encoding=3, lang="eng", desc="", text=[comment]))

    tags.delall("APIC")
    for picture in source.pictures:
        tags.add(
            APIC(
                encoding=3,
                mime=picture.mime or "image/jpeg",
                type=picture.type,
                desc=picture.desc or "Cover",
                data=picture.data,
            )
        )
    if tags:
        tags.save(output_path, v2_version=3)


def transcode_flac_file(
    source_path: str | os.PathLike[str],
    output_path: str | os.PathLike[str],
    options: FlacMp3Options | None = None,
    *,
    cancel_check: CancelCheck | None = None,
    progress_callback: FileProgressCallback | None = None,
) -> FlacMp3Result:
    options = (options or FlacMp3Options()).normalized()
    source = Path(source_path)
    destination = Path(output_path)
    cancel_check = cancel_check or (lambda: False)
    progress_callback = progress_callback or (lambda _percent: None)

    if source.suffix.casefold() != ".flac" or not source.is_file():
        return FlacMp3Result(str(source), str(destination), FlacMp3Status.FAILED, "Source is not a FLAC file.")
    if destination.exists() and not options.overwrite:
        if is_valid_mp3(destination):
            return FlacMp3Result(str(source), str(destination), FlacMp3Status.SKIPPED)
        return FlacMp3Result(
            str(source),
            str(destination),
            FlacMp3Status.FAILED,
            "The output path already exists but is not a valid MP3 file.",
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{destination.name}.{uuid.uuid4().hex}.part"
    try:
        if cancel_check():
            raise TranscodeCanceled()
        with sf.SoundFile(source, mode="r") as audio:
            if audio.frames <= 0 or audio.samplerate <= 0 or audio.channels <= 0:
                raise ValueError("The FLAC file does not contain usable audio data.")
            encoder: lameenc.Encoder | None = None
            processed = 0
            with temporary.open("wb") as handle:
                while True:
                    if cancel_check():
                        raise TranscodeCanceled()
                    block = audio.read(options.block_frames, dtype="int16", always_2d=True)
                    if len(block) == 0:
                        break
                    pcm, channels = _pcm_for_mp3(block)
                    if encoder is None:
                        encoder = lameenc.Encoder()
                        encoder.set_channels(channels)
                        encoder.set_in_sample_rate(int(audio.samplerate))
                        encoder.set_out_sample_rate(_output_sample_rate(int(audio.samplerate)))
                        encoder.set_bit_rate(options.bitrate_kbps)
                        encoder.set_quality(options.quality)
                    handle.write(encoder.encode(pcm.tobytes(order="C")))
                    processed += len(block)
                    progress_callback(min(processed * 100.0 / audio.frames, 99.5))
                if encoder is None:
                    raise ValueError("The FLAC file does not contain usable audio data.")
                handle.write(encoder.flush())

        if cancel_check():
            raise TranscodeCanceled()
        _copy_flac_metadata(source, temporary)
        if not is_valid_mp3(temporary):
            raise ValueError("Encoded output failed MP3 validation.")
        if cancel_check():
            raise TranscodeCanceled()
        os.replace(temporary, destination)
        progress_callback(100.0)
        return FlacMp3Result(str(source), str(destination), FlacMp3Status.CONVERTED)
    except TranscodeCanceled:
        return FlacMp3Result(str(source), str(destination), FlacMp3Status.CANCELED)
    except Exception as exc:
        return FlacMp3Result(str(source), str(destination), FlacMp3Status.FAILED, str(exc))
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


class _RateLimitedProgress:
    def __init__(self, callback: ProgressCallback | None) -> None:
        self.callback = callback
        self.sequence = 0
        self.last_emit = 0.0
        self.last_percent = 0.0

    def emit(self, progress: FlacMp3Progress, *, force: bool = False) -> None:
        if not self.callback:
            return
        now = time.monotonic()
        percent = max(self.last_percent, min(100.0, float(progress.overall_percent)))
        if not force and now - self.last_emit < 0.1:
            return
        self.sequence += 1
        self.last_emit = now
        self.last_percent = percent
        progress.sequence = self.sequence
        progress.overall_percent = percent
        self.callback(deepcopy(progress))


def transcode_flac_batch(
    jobs: Sequence[FlacMp3Job],
    options: FlacMp3Options | None = None,
    *,
    cancel_event: threading.Event | None = None,
    progress_callback: ProgressCallback | None = None,
) -> FlacMp3Progress:
    options = (options or FlacMp3Options()).normalized()
    cancel_event = cancel_event or threading.Event()
    total = len(jobs)
    progress = FlacMp3Progress(total=total, not_processed=total)
    emitter = _RateLimitedProgress(progress_callback)
    emitter.emit(progress, force=True)

    for index, job in enumerate(jobs):
        if cancel_event.is_set():
            break
        progress.current_file = job.source_path
        progress.current_percent = 0.0
        progress.current_status = FlacMp3Status.CONVERTING

        def on_file_progress(value: float, *, item_index: int = index) -> None:
            progress.current_percent = max(progress.current_percent, value)
            progress.overall_percent = ((item_index + progress.current_percent / 100.0) / max(total, 1)) * 100.0
            emitter.emit(progress)

        emitter.emit(progress, force=True)
        result = transcode_flac_file(
            job.source_path,
            job.output_path,
            options,
            cancel_check=cancel_event.is_set,
            progress_callback=on_file_progress,
        )
        progress.results.append(result)
        progress.current_status = result.status
        progress.current_percent = 100.0 if result.status is not FlacMp3Status.CANCELED else progress.current_percent
        progress.completed += 1
        progress.not_processed = max(total - progress.completed, 0)
        if result.status is FlacMp3Status.CONVERTED:
            progress.converted += 1
        elif result.status is FlacMp3Status.SKIPPED:
            progress.skipped += 1
        elif result.status is FlacMp3Status.FAILED:
            progress.failed += 1
        elif result.status is FlacMp3Status.CANCELED:
            progress.canceled_count += 1
            cancel_event.set()
        progress.overall_percent = (progress.completed / max(total, 1)) * 100.0
        emitter.emit(progress, force=True)

    if cancel_event.is_set() and progress.not_processed:
        for job in jobs[progress.completed:]:
            progress.results.append(
                FlacMp3Result(job.source_path, job.output_path, FlacMp3Status.NOT_PROCESSED)
            )
    progress.canceled = cancel_event.is_set()
    progress.current_file = ""
    progress.current_percent = 0.0
    progress.current_status = FlacMp3Status.CANCELED if cancel_event.is_set() else FlacMp3Status.CONVERTED
    if not cancel_event.is_set():
        progress.overall_percent = 100.0 if total else 0.0
    emitter.emit(progress, force=True)
    return progress


__all__ = [
    "FlacMp3Job",
    "FlacMp3Options",
    "FlacMp3Progress",
    "FlacMp3Result",
    "FlacMp3Status",
    "TranscodeCanceled",
    "discover_flac_files",
    "is_valid_mp3",
    "output_path_for",
    "transcode_flac_batch",
    "transcode_flac_file",
]
