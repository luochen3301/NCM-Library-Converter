from __future__ import annotations

import hashlib
import tempfile
import threading
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf
from mutagen.flac import FLAC, Picture
from mutagen.mp3 import MP3

from ncmdump.audio_transcoder import (
    FlacMp3Job,
    FlacMp3Options,
    FlacMp3Status,
    discover_flac_files,
    is_valid_mp3,
    output_path_for,
    transcode_flac_batch,
    transcode_flac_file,
)


class FlacMp3ServiceTests(unittest.TestCase):
    def _flac(
        self,
        path: Path,
        *,
        sample_rate: int = 44_100,
        seconds: float = 0.25,
        channels: int = 2,
    ) -> Path:
        frames = max(1, int(sample_rate * seconds))
        tone = np.sin(2 * np.pi * 440 * np.arange(frames) / sample_rate) * 0.35
        audio = np.column_stack([tone] * channels) if channels > 1 else tone
        sf.write(path, audio, sample_rate, format="FLAC", subtype="PCM_24")
        return path

    @staticmethod
    def _digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_discovery_handles_unicode_case_and_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "中文 音乐"
            nested = root / "Album"
            nested.mkdir(parents=True)
            first = self._flac(root / "第一首.FLAC")
            second = self._flac(nested / "second.flac")
            (nested / "ignore.mp3").write_bytes(b"not relevant")

            discovered = discover_flac_files([root, first], recursive=True)

            self.assertEqual({Path(path) for path in discovered}, {first.resolve(), second.resolve()})

    def test_output_path_preserves_relative_structure(self):
        source = Path("C:/Music/Artist/Album/song.flac")
        output = output_path_for(
            source,
            "D:/MP3",
            relative_root="C:/Music",
            preserve_structure=True,
        )
        self.assertEqual(Path(output), Path("D:/MP3/Artist/Album/song.mp3"))

    def test_high_rate_conversion_preserves_source_and_common_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._flac(root / "测试 歌曲.flac", sample_rate=96_000)
            source_audio = FLAC(source)
            source_audio["title"] = "测试标题"
            source_audio["artist"] = "Test Artist"
            source_audio["album"] = "Test Album"
            picture = Picture()
            picture.mime = "image/png"
            picture.type = 3
            picture.desc = "Cover"
            picture.data = b"\x89PNG\r\n\x1a\nmock-cover"
            source_audio.add_picture(picture)
            source_audio.save()
            before = self._digest(source)
            output = root / "output" / "测试 歌曲.mp3"

            result = transcode_flac_file(source, output, FlacMp3Options(320))

            self.assertEqual(result.status, FlacMp3Status.CONVERTED)
            self.assertTrue(is_valid_mp3(output))
            self.assertEqual(before, self._digest(source))
            mp3 = MP3(output)
            self.assertEqual(mp3.info.sample_rate, 48_000)
            self.assertEqual(str(mp3.tags["TIT2"]), "测试标题")
            self.assertEqual(str(mp3.tags["TPE1"]), "Test Artist")
            self.assertEqual(len(mp3.tags.getall("APIC")), 1)

    def test_multichannel_flac_downmixes_to_stereo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._flac(root / "surround.flac", channels=6)
            output = root / "surround.mp3"

            result = transcode_flac_file(source, output, FlacMp3Options(192))

            self.assertEqual(result.status, FlacMp3Status.CONVERTED)
            self.assertEqual(MP3(output).info.channels, 2)

    def test_valid_existing_output_is_skipped_and_invalid_existing_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._flac(root / "source.flac")
            output = root / "source.mp3"
            first = transcode_flac_file(source, output, FlacMp3Options(256))
            self.assertEqual(first.status, FlacMp3Status.CONVERTED)
            before = self._digest(output)

            skipped = transcode_flac_file(source, output, FlacMp3Options(128))
            self.assertEqual(skipped.status, FlacMp3Status.SKIPPED)
            self.assertEqual(before, self._digest(output))

            output.write_bytes(b"invalid existing data")
            invalid_before = self._digest(output)
            failed = transcode_flac_file(source, output, FlacMp3Options(320))
            self.assertEqual(failed.status, FlacMp3Status.FAILED)
            self.assertEqual(invalid_before, self._digest(output))

    def test_overwrite_uses_valid_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._flac(root / "source.flac")
            output = root / "source.mp3"
            output.write_bytes(b"old invalid output")

            result = transcode_flac_file(source, output, FlacMp3Options(192, overwrite=True))

            self.assertEqual(result.status, FlacMp3Status.CONVERTED)
            self.assertTrue(is_valid_mp3(output))

    def test_cancel_removes_temporary_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._flac(root / "long.flac", seconds=2.0)
            output = root / "long.mp3"
            cancel_event = threading.Event()

            result = transcode_flac_file(
                source,
                output,
                FlacMp3Options(320, block_frames=4_096),
                cancel_check=cancel_event.is_set,
                progress_callback=lambda _value: cancel_event.set(),
            )

            self.assertEqual(result.status, FlacMp3Status.CANCELED)
            self.assertFalse(output.exists())
            self.assertEqual(list(root.glob(".*.part")), [])

    def test_batch_progress_is_monotonic_and_classifies_unprocessed_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sources = [self._flac(root / f"{index}.flac") for index in range(3)]
            jobs = [FlacMp3Job(str(path), str(path.with_suffix(".mp3"))) for path in sources]
            cancel_event = threading.Event()
            events = []

            def on_progress(progress):
                events.append(progress)
                if progress.current_status is FlacMp3Status.CONVERTING:
                    cancel_event.set()

            result = transcode_flac_batch(
                jobs,
                FlacMp3Options(128),
                cancel_event=cancel_event,
                progress_callback=on_progress,
            )

            self.assertTrue(result.canceled)
            self.assertEqual(result.canceled, True)
            self.assertEqual(result.not_processed, 2)
            self.assertEqual([item.status for item in result.results], [
                FlacMp3Status.CANCELED,
                FlacMp3Status.NOT_PROCESSED,
                FlacMp3Status.NOT_PROCESSED,
            ])
            percentages = [event.overall_percent for event in events]
            self.assertEqual(percentages, sorted(percentages))
            self.assertEqual([event.sequence for event in events], list(range(1, len(events) + 1)))


if __name__ == "__main__":
    unittest.main()
