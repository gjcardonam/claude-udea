import json
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock, patch

from transcribe_missing import (
    WhisperSettings,
    _recording_transcripts,
    _whisper_destination,
    find_missing,
    settings_from_args,
    transcribe_all,
)
from claude_udea.download import copy_transcripts, rename_downloads


class WhisperTranscriptionTests(unittest.TestCase):
    whisper_vtt = (
        "WEBVTT\n\nNOTE\nTranscripcion generada localmente con faster-whisper\n\n"
        "1\n00:00:00.000 --> 00:00:01.000\nHola\n"
    )

    def slot_fixture(self, work_dir, parts=(None, 1, 2), url=True):
        course_dir = work_dir / "downloads" / "architecture"
        course_dir.mkdir(parents=True)
        info = {
            "start_date": "2026-09-01T10:00:00Z",
            "organized_files": [],
        }
        if url:
            info["url"] = "https://zoom.example/rec-1"
        for part in parts:
            label = f" - Parte {part}" if part else ""
            name = f"Clase #1 - 2026-09-01{label}.mp4"
            (course_dir / name).write_bytes(name.encode())
            info["organized_files"].append(name)
        recordings = {"architecture": {"recordings": {"rec-1": info}}}
        (work_dir / "recordings.json").write_text(json.dumps(recordings), encoding="utf-8")
        return course_dir, recordings

    def run_slots(self, work_dir, transcribe_effect=None, **kwargs):
        faster_whisper = ModuleType("faster_whisper")
        faster_whisper.WhisperModel = Mock(return_value=Mock())

        def extract(source, remove_video=True):
            self.assertFalse(remove_video)
            wav = source.with_suffix(".wav")
            wav.write_bytes(source.read_bytes())
            return wav

        def transcribe(_model, _wav, destination, _parts, _settings):
            destination.write_text(self.whisper_vtt, encoding="utf-8")

        with (
            patch.dict("sys.modules", {"faster_whisper": faster_whisper}),
            patch("transcribe_missing.download_video") as download,
            patch("transcribe_missing.extract_audio", side_effect=extract) as extraction,
            patch("transcribe_missing.transcribe", side_effect=transcribe_effect or transcribe) as transcription,
        ):
            result = transcribe_all(work_dir, **kwargs)
        download.assert_not_called()
        return result, extraction, transcription

    def test_preexisting_whisper_defaults_are_preserved(self):
        settings = WhisperSettings()
        self.assertEqual((settings.model, settings.compute_type, settings.beam_size), ("medium", "int8", 1))
        self.assertFalse(settings.condition_on_previous_text)

    def test_transcribes_primary_and_all_parts_without_url_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            work_dir = Path(temporary_directory)
            course_dir, _ = self.slot_fixture(work_dir, url=False)
            result, extraction, transcription = self.run_slots(work_dir)
            self.assertEqual(result, (3, 0))
            self.assertEqual(extraction.call_count, 3)
            expected = [
                "Clase #1 - 2026-09-01.whisper.transcript.vtt",
                "Clase #1 - 2026-09-01 - Parte 1.whisper.transcript.vtt",
                "Clase #1 - 2026-09-01 - Parte 2.whisper.transcript.vtt",
            ]
            self.assertEqual([call.args[2].name for call in transcription.call_args_list], expected)
            self.assertEqual(len({call.args[1] for call in transcription.call_args_list}), 3)
            self.assertEqual(len({call.args[3] for call in transcription.call_args_list}), 3)
            self.assertEqual(len(list(course_dir.glob("*.mp4"))), 3)
            self.assertEqual(transcribe_all(work_dir), (0, 0))
            self.assertEqual(find_missing(work_dir)[1], [])

    def test_legacy_small_txt_does_not_block_medium_transcript_and_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            work_dir = Path(temporary_directory)
            course_dir, recordings = self.slot_fixture(work_dir, parts=(None,))
            legacy_dir = course_dir / "transcripts" / "whisper" / "whisper con bajo"
            legacy_dir.mkdir(parents=True)
            legacy = legacy_dir / "Clase #1 - 2026-09-01.whisper.transcript.txt"
            legacy.write_text(
                "WEBVTT\n\nNOTE\nTranscripción generada localmente con faster-whisper (small, int8)\n\n"
                "1\n00:00:00.000 --> 00:00:01.000\nsmall\n",
                encoding="utf-8",
            )
            recordings["architecture"]["recordings"]["rec-1"]["organized_files"].append(
                "transcripts/whisper/whisper con bajo/" + legacy.name
            )
            (work_dir / "recordings.json").write_text(json.dumps(recordings), encoding="utf-8")

            self.assertEqual(len(_recording_transcripts(
                course_dir, "rec-1", recordings["architecture"]["recordings"]["rec-1"],
            )), 0)
            self.assertEqual(find_missing(work_dir)[1][0]["rec_id"], "rec-1")
            result, _, _ = self.run_slots(work_dir)
            self.assertEqual(result, (1, 0))
            self.assertTrue(legacy.exists())
            active = course_dir / "transcripts" / "whisper" / "Clase #1 - 2026-09-01.whisper.transcript.vtt"
            self.assertTrue(active.is_file())

    def test_legacy_whisper_txt_is_not_deleted_when_zoom_is_not_kept(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            work_dir = Path(temporary_directory)
            course_dir, recordings = self.slot_fixture(work_dir, parts=(None,))
            legacy_dir = course_dir / "transcripts" / "whisper" / "whisper con bajo"
            legacy_dir.mkdir(parents=True)
            legacy = legacy_dir / "Clase #1 - 2026-09-01.whisper.transcript.txt"
            legacy.write_text("WEBVTT\nsmall\n", encoding="utf-8")
            info = recordings["architecture"]["recordings"]["rec-1"]
            info["organized_files"].append("transcripts/whisper/whisper con bajo/" + legacy.name)
            (work_dir / "recordings.json").write_text(json.dumps(recordings), encoding="utf-8")

            result, _, _ = self.run_slots(work_dir, keep_zoom_transcripts=False)

            self.assertEqual(result, (1, 0))
            self.assertTrue(legacy.exists())

    def test_settings_flags_accept_equals_and_reject_invalid_chunk_size(self):
        settings = settings_from_args([
            "--whisper-model=medium", "--whisper-beam-size", "2",
            "--whisper-chunk-seconds=600", "--whisper-no-conditioning",
        ])
        self.assertEqual((settings.model, settings.beam_size, settings.chunk_seconds), ("medium", 2, 600))
        self.assertFalse(settings.condition_on_previous_text)
        with self.assertRaises(ValueError):
            settings_from_args(["--whisper-chunk-seconds", "0"])

    def test_chunk_cache_is_invalidated_when_settings_or_chunk_count_changes(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            wav = root / "audio.wav"
            wav.write_bytes(b"audio")
            parts = root / "parts"
            settings = WhisperSettings(chunk_seconds=1)
            with (
                patch("transcribe_missing.wav_duration", return_value=2.5),
                patch("transcribe_missing.extract_chunk_audio", side_effect=lambda _wav, chunk, _offset, _length: chunk.write_bytes(b"chunk")),
            ):
                model = Mock()
                model.transcribe.side_effect = lambda *_args, **_kwargs: (
                    iter([Mock(start=0, end=0.5, text="hello")]), None,
                )
                from transcribe_missing import transcribe

                transcribe(model, wav, root / "first.vtt", parts, settings)
                self.assertEqual(len(list(parts.glob("part*.json"))), 3)
                transcribe(model, wav, root / "second.vtt", parts, WhisperSettings(chunk_seconds=2))
                self.assertEqual(len(list(parts.glob("part*.json"))), 2)
                self.assertEqual(model.transcribe.call_count, 5)

    def test_chunk_cache_without_manifest_is_not_reused(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            wav = root / "audio.wav"
            wav.write_bytes(b"audio")
            parts = root / "parts"
            parts.mkdir()
            (parts / "part000.json").write_text("[]", encoding="utf-8")
            model = Mock()
            model.transcribe.return_value = (iter([Mock(start=0, end=0.5, text="hello")]), None)
            from transcribe_missing import transcribe
            with (
                patch("transcribe_missing.wav_duration", return_value=1.0),
                patch("transcribe_missing.extract_chunk_audio", side_effect=lambda _wav, chunk, _offset, _length: chunk.write_bytes(b"chunk")),
            ):
                transcribe(model, wav, root / "output.vtt", parts, WhisperSettings(chunk_seconds=5))
            model.transcribe.assert_called_once()

    def test_cli_whisper_values_are_not_treated_as_course_slugs(self):
        from claude_udea.cli import _filter_course_args

        remaining = _filter_course_args([
            "modelos-y-simulacion-de-sistemas-ii", "--whisper-model", "medium",
            "--whisper-beam-size=1", "--class", "9", "--class", "10",
        ])
        self.assertEqual(remaining, ["modelos-y-simulacion-de-sistemas-ii"])

    def test_cli_flags_can_explicitly_keep_zoom_transcripts_noninteractively(self):
        from transcribe_missing import main

        with tempfile.TemporaryDirectory() as temporary_directory:
            work_dir = Path(temporary_directory)
            self.slot_fixture(work_dir, parts=(None,))
            zoom = work_dir / "downloads" / "architecture" / "Clase #1 - 2026-09-01.cc.vtt"
            zoom.write_text("WEBVTT\n", encoding="utf-8")
            with (
                patch("sys.argv", ["transcribe_missing.py", "--work-dir", str(work_dir), "--always-whisper", "--keep-zoom-transcripts", "--check"]),
                patch("builtins.input") as prompt,
                patch("transcribe_missing.log"),
                patch("transcribe_missing.transcribe_all", return_value=(0, 0)),
                self.assertRaises(SystemExit) as exit_result,
            ):
                main()
            self.assertEqual(exit_result.exception.code, 0)
            prompt.assert_not_called()

    def test_no_speech_marker_skips_slot_without_creating_empty_vtt(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            work_dir = Path(temporary_directory)
            course_dir, _ = self.slot_fixture(work_dir, parts=(None,))
            from transcribe_missing import _no_speech_marker, _build_rec_id_map
            recordings = json.loads((work_dir / "recordings.json").read_text(encoding="utf-8"))
            meta = _build_rec_id_map(recordings)["rec-1"]
            marker = _no_speech_marker(course_dir, meta, course_dir / "Clase #1 - 2026-09-01.mp4")
            marker.parent.mkdir(parents=True, exist_ok=True)
            video = course_dir / "Clase #1 - 2026-09-01.mp4"
            marker.write_text(json.dumps({
                "status": "no-speech",
                "model": "medium",
                "compute_type": "int8",
                "source": [str(video.resolve()), video.stat().st_size, video.stat().st_mtime_ns],
            }), encoding="utf-8")
            result, _, _ = self.run_slots(work_dir)
            self.assertEqual(result, (0, 0))
            self.assertTrue(marker.exists())
            self.assertFalse((course_dir / "transcripts" / "whisper" / "Clase #1 - 2026-09-01.whisper.transcript.vtt").exists())

    def test_completed_part_does_not_skip_other_slots_or_get_deleted(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            work_dir = Path(temporary_directory)
            course_dir, _ = self.slot_fixture(work_dir)
            completed = course_dir / "Clase #1 - 2026-09-01 - Parte 2.transcript.vtt"
            completed.write_text(self.whisper_vtt, encoding="utf-8")
            zoom = course_dir / "Clase #1 - 2026-09-01.transcript.vtt"
            zoom.write_text("WEBVTT\nZoom", encoding="utf-8")
            missing = find_missing(work_dir)[1]
            self.assertEqual(len(missing), 1)
            self.assertIn("Parte 1", missing[0]["title"])
            result, _, transcription = self.run_slots(work_dir)
            self.assertEqual(result, (2, 0))
            self.assertNotIn("Parte 2", " ".join(call.args[2].name for call in transcription.call_args_list))
            self.assertEqual(completed.read_text(encoding="utf-8"), self.whisper_vtt)
            self.assertTrue(zoom.exists())

    def test_cleanup_is_limited_to_successful_slot(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            work_dir = Path(temporary_directory)
            course_dir, _ = self.slot_fixture(work_dir, parts=(1,))
            other_whisper = course_dir / "Clase #1 - 2026-09-01 - Parte 2.transcript.vtt"
            other_whisper.write_text(self.whisper_vtt, encoding="utf-8")
            same_whisper = course_dir / "Clase #1 - 2026-09-01 - Parte 1.transcript.vtt"
            same_whisper.write_text("WEBVTT\nNOTE\ngenerada localmente con faster-whisper\n", encoding="utf-8")
            zooms = []
            for label in ("", " - Parte 1", " - Parte 2"):
                zoom = course_dir / f"Clase #1 - 2026-09-01{label}.cc.vtt"
                zoom.write_text("WEBVTT\nZoom", encoding="utf-8")
                zooms.append(zoom)
            result, _, _ = self.run_slots(work_dir, keep_zoom_transcripts=False)
            self.assertEqual(result, (1, 0))
            self.assertFalse(same_whisper.exists())
            self.assertTrue(other_whisper.exists())
            self.assertEqual([zoom.exists() for zoom in zooms], [True, False, True])

    def test_failed_slot_resumes_its_own_audio_and_chunks(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            work_dir = Path(temporary_directory)
            self.slot_fixture(work_dir, parts=(None, 1))
            failed_cache = []

            def fail_part(_model, wav, destination, parts_dir, _settings):
                if "Parte 1" in destination.name:
                    parts_dir.mkdir()
                    (parts_dir / "part000.json").write_text("[]", encoding="utf-8")
                    failed_cache.append((wav, parts_dir, wav.read_bytes()))
                    raise RuntimeError("interrupted")
                destination.write_text(self.whisper_vtt, encoding="utf-8")

            self.assertEqual(self.run_slots(work_dir, fail_part)[0], (1, 1))
            wav, parts_dir, audio = failed_cache[0]
            self.assertTrue(wav.exists())

            def resume(_model, resumed_wav, destination, resumed_parts, _settings):
                self.assertEqual((resumed_wav, resumed_parts), (wav, parts_dir))
                self.assertEqual(resumed_wav.read_bytes(), audio)
                self.assertTrue((resumed_parts / "part000.json").exists())
                destination.write_text(self.whisper_vtt, encoding="utf-8")

            result, extraction, _ = self.run_slots(work_dir, resume)
            self.assertEqual(result, (1, 0))
            extraction.assert_not_called()
            self.assertFalse(wav.exists())

    def test_stale_date_category_and_backup_files_are_excluded(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            work_dir = Path(temporary_directory)
            course_dir, recordings = self.slot_fixture(work_dir, parts=(2,))
            stale = []
            for base in ("Clase #1 - 2026-08-01", "Fabrica Escuela - Clase #1 - 2026-09-01"):
                for suffix in (".mp4", ".transcript.vtt"):
                    path = course_dir / f"{base} [rec-1]{suffix}"
                    path.write_text(self.whisper_vtt, encoding="utf-8")
                    stale.append(path)
            backup = course_dir / ".claude-udea-backup"
            backup.mkdir()
            (backup / "Clase #1 - 2026-09-01.mp4").write_bytes(b"backup")
            info = recordings["architecture"]["recordings"]["rec-1"]
            info["organized_files"].extend(path.name for path in stale)
            (work_dir / "recordings.json").write_text(json.dumps(recordings), encoding="utf-8")
            self.assertEqual(len(find_missing(work_dir)[1]), 1)
            result, extraction, _ = self.run_slots(work_dir, keep_zoom_transcripts=False)
            self.assertEqual(result, (1, 0))
            self.assertIn("Parte 2", extraction.call_args.args[0].name)
            self.assertTrue(all(path.exists() for path in stale))

    def test_check_reports_each_pending_slot_without_processing(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            work_dir = Path(temporary_directory)
            self.slot_fixture(work_dir)
            with patch("transcribe_missing.log") as log:
                self.assertEqual(transcribe_all(work_dir, check_only=True), (0, 0))
            pending = [call.args[0] for call in log.call_args_list if "  - " in call.args[0]]
            self.assertEqual(len(pending), 3)
            self.assertFalse((work_dir / ".media-cache").exists())

    def test_missing_only_preserves_zoom_and_transcribes_only_uncovered_parts(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            work_dir = Path(temporary_directory)
            course_dir, _ = self.slot_fixture(work_dir)
            primary = course_dir / "Clase #1 - 2026-09-01.transcript.vtt"
            primary.write_text(self.whisper_vtt, encoding="utf-8")
            zoom = course_dir / "Clase #1 - 2026-09-01 - Parte 1.cc.vtt"
            zoom.write_text("WEBVTT\nZoom", encoding="utf-8")
            empty = course_dir / "Clase #1 - 2026-09-01 - Parte 2.transcript.vtt"
            empty.write_text("WEBVTT\nNOTE\ngenerada localmente con faster-whisper\n", encoding="utf-8")
            result, extraction, transcription = self.run_slots(work_dir, only_missing=True)
            self.assertEqual(result, (1, 0))
            self.assertIn("Parte 2", extraction.call_args.args[0].name)
            self.assertIn("Parte 2", transcription.call_args.args[2].name)
            self.assertTrue(primary.exists())
            self.assertTrue(zoom.exists())
            self.assertFalse(empty.exists())

    def test_alias_primary_and_organized_parts_are_all_discovered(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            work_dir = Path(temporary_directory)
            course_dir, _ = self.slot_fixture(work_dir, parts=(1, 2))
            alias_video = course_dir / "Architecture [rec-1].mp4"
            alias_video.write_bytes(b"primary")
            result, extraction, _ = self.run_slots(work_dir)
            self.assertEqual(result, (3, 0))
            self.assertEqual(extraction.call_args_list[0].args[0], alias_video)

    def test_empty_slot_does_not_remove_zoom_or_other_slots(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            work_dir = Path(temporary_directory)
            course_dir, _ = self.slot_fixture(work_dir, parts=(2,))
            zoom = course_dir / "Clase #1 - 2026-09-01 - Parte 2.cc.vtt"
            zoom.write_text("WEBVTT\nZoom", encoding="utf-8")
            primary = course_dir / "Clase #1 - 2026-09-01.transcript.vtt"
            primary.write_text(self.whisper_vtt, encoding="utf-8")

            def empty(_model, _wav, destination, _parts, _settings):
                destination.write_text("WEBVTT\nNOTE\ngenerada localmente con faster-whisper\n", encoding="utf-8")

            result, _, transcription = self.run_slots(work_dir, empty, keep_zoom_transcripts=False)
            self.assertEqual(result, (0, 1))
            self.assertTrue(zoom.exists())
            self.assertTrue(primary.exists())
            self.assertFalse(transcription.call_args.args[2].exists())
            self.assertTrue(transcription.call_args.args[1].exists())

    def test_cli_check_always_whisper_does_not_prompt_or_load_model(self):
        from transcribe_missing import main

        with tempfile.TemporaryDirectory() as temporary_directory:
            work_dir = Path(temporary_directory)
            course_dir, _ = self.slot_fixture(work_dir, parts=(2,))
            (course_dir / "Clase #1 - 2026-09-01 - Parte 2.cc.vtt").write_text("WEBVTT\n", encoding="utf-8")
            with (
                patch("sys.argv", ["transcribe_missing.py", "--work-dir", str(work_dir), "--always-whisper", "--check"]),
                patch("builtins.input") as prompt,
                patch("transcribe_missing.extract_audio") as extraction,
                patch("transcribe_missing.log") as log,
                self.assertRaises(SystemExit) as exit_result,
            ):
                main()
            self.assertEqual(exit_result.exception.code, 0)
            prompt.assert_not_called()
            extraction.assert_not_called()
            self.assertTrue(any("Parte 2.whisper.transcript.vtt" in call.args[0] for call in log.call_args_list))
            self.assertFalse((work_dir / ".media-cache").exists())

    def test_download_fallback_uses_primary_destination_and_resumes_without_download(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            work_dir = Path(temporary_directory)
            course_dir, _ = self.slot_fixture(work_dir, parts=())
            faster_whisper = ModuleType("faster_whisper")
            faster_whisper.WhisperModel = Mock(return_value=Mock())

            def download(_rec, cache_dir):
                video = cache_dir / "Downloaded [rec-1].mp4"
                video.write_bytes(b"video")
                return video

            def extract(video, remove_video=True):
                self.assertTrue(remove_video)
                wav = video.with_suffix(".wav")
                wav.write_bytes(b"audio")
                video.unlink()
                return wav

            with (
                patch.dict("sys.modules", {"faster_whisper": faster_whisper}),
                patch("transcribe_missing.download_video", side_effect=download) as downloader,
                patch("transcribe_missing.extract_audio", side_effect=extract) as extraction,
                patch("transcribe_missing.transcribe", side_effect=RuntimeError("interrupted")),
            ):
                self.assertEqual(transcribe_all(work_dir), (0, 1))
            downloader.assert_called_once()
            extraction.assert_called_once()
            result, extraction, transcription = self.run_slots(work_dir)
            self.assertEqual(result, (1, 0))
            extraction.assert_not_called()
            self.assertEqual(transcription.call_args.args[2].name, "Clase #1 - 2026-09-01.whisper.transcript.vtt")
            self.assertTrue((course_dir / "transcripts" / "whisper" / transcription.call_args.args[2].name).exists())

    def test_whisper_destination_follows_video_part(self):
        from claude_udea.download import _build_rec_id_map

        recordings = {
            "architecture": {
                "recordings": {
                    "rec-1": {
                        "title": "Architecture",
                        "start_date": "2026-09-01T10:00:00Z",
                    }
                }
            }
        }
        meta = _build_rec_id_map(recordings)["rec-1"]
        with tempfile.TemporaryDirectory() as temporary_directory:
            course_dir = Path(temporary_directory)
            video = course_dir / "videos" / "Clase #1 - 2026-09-01 - Parte 2.mp4"
            destination = _whisper_destination(course_dir, meta, video)

        self.assertEqual(
            destination.as_posix(),
            (course_dir / "transcripts" / "whisper" / "Clase #1 - 2026-09-01 - Parte 2.whisper.transcript.vtt").as_posix(),
        )

    def test_whisper_replaces_zoom_transcript_and_preserves_video(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            work_dir = Path(temporary_directory)
            course_dir = work_dir / "downloads" / "software-architecture"
            course_dir.mkdir(parents=True)
            video = course_dir / "Architecture [recording-123].mp4"
            video.write_bytes(b"video")
            zoom_vtt = course_dir / "Architecture [recording-123].transcript.vtt"
            zoom_vtt.write_text("WEBVTT\n\nZoom subtitles\n", encoding="utf-8")
            recordings = {
                "software-architecture": {
                    "name": "Software Architecture",
                    "recordings": {
                        "recording-123": {
                            "title": "Architecture",
                            "url": "https://zoom.example/recording-123",
                            "start_date": "2026-02-01T10:00:00Z",
                            "duration_minutes": 55,
                        }
                    },
                }
            }
            (work_dir / "recordings.json").write_text(
                json.dumps(recordings),
                encoding="utf-8",
            )

            faster_whisper = ModuleType("faster_whisper")
            faster_whisper.WhisperModel = Mock(return_value=Mock())

            def extract_audio_side_effect(source, remove_video=True):
                wav = source.with_suffix(".wav")
                wav.write_bytes(b"audio")
                return wav

            def transcribe_side_effect(model, wav, destination, parts_dir, settings=None):
                destination.write_text(
                    "WEBVTT\n\nNOTE\nTranscripción generada localmente con faster-whisper\n\n"
                    "1\n00:00:00.000 --> 00:00:01.000\nHola\n",
                    encoding="utf-8",
                )

            with (
                patch.dict("sys.modules", {"faster_whisper": faster_whisper}),
                patch("transcribe_missing.extract_audio", side_effect=extract_audio_side_effect),
                patch("transcribe_missing.transcribe", side_effect=transcribe_side_effect),
            ):
                result = transcribe_all(work_dir, keep_zoom_transcripts=True)

            whisper_transcript = (
                course_dir / "transcripts" / "whisper"
                / "Clase #1 - 2026-02-01.whisper.transcript.vtt"
            )
            self.assertEqual(result, (1, 0))
            self.assertTrue(whisper_transcript.is_file())
            self.assertFalse(list(course_dir.glob("*.whisper.transcript.vtt")))
            self.assertIn("faster-whisper", whisper_transcript.read_text(encoding="utf-8"))
            self.assertTrue(video.exists())

            rename_downloads(work_dir / "downloads", recordings)
            copy_transcripts(work_dir / "downloads", recordings)
            centralized = (
                work_dir / "downloads" / "transcripts" / "software-architecture"
                / whisper_transcript.name
            )
            self.assertTrue(centralized.is_file())
            self.assertIn("Zoom subtitles", (
                course_dir / "transcripts" / "zoom"
                / "Clase #1 - 2026-02-01.transcript.vtt"
            ).read_text(encoding="utf-8"))
            index = json.loads(
                (work_dir / "downloads" / "transcripts" / "index.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                next(
                    entry["source"]
                    for entry in index["software-architecture"]["files"]
                    if entry["file"] == whisper_transcript.name
                ),
                "faster-whisper",
            )

    def test_fabrica_escuela_uses_its_class_name_and_folder(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            work_dir = Path(temporary_directory)
            course_dir = work_dir / "downloads" / "arquitectura-de-software"
            course_dir.mkdir(parents=True)
            (work_dir / "recordings.json").write_text(
                json.dumps({
                    "arquitectura-de-software": {
                        "name": "Arquitectura de Software",
                        "recordings": {
                            "fabrica-1": {
                                "title": "Fábrica Escuela - Introducción",
                                "url": "https://zoom.example/fabrica-1",
                                "start_date": "2026-02-01T10:00:00Z",
                            }
                        },
                    }
                }),
                encoding="utf-8",
            )
            (course_dir / "Clase [fabrica-1].mp4").write_bytes(b"video")
            faster_whisper = ModuleType("faster_whisper")
            faster_whisper.WhisperModel = Mock(return_value=Mock())

            def extract_audio_side_effect(source, remove_video=True):
                wav = source.with_suffix(".wav")
                wav.write_bytes(b"audio")
                return wav

            def transcribe_side_effect(_model, _wav, destination, _parts_dir, _settings=None):
                destination.write_text(
                    "WEBVTT\n\nNOTE\nTranscripción generada localmente con faster-whisper\n"
                    "\n1\n00:00:00.000 --> 00:00:01.000\nHola\n",
                    encoding="utf-8",
                )

            with (
                patch.dict("sys.modules", {"faster_whisper": faster_whisper}),
                patch("transcribe_missing.extract_audio", side_effect=extract_audio_side_effect),
                patch("transcribe_missing.transcribe", side_effect=transcribe_side_effect),
            ):
                self.assertEqual(transcribe_all(work_dir), (1, 0))

            self.assertTrue(
                (
                    course_dir / "transcripts" / "whisper"
                    / "Fabrica Escuela - Clase #1 - 2026-02-01.whisper.transcript.vtt"
                ).is_file()
            )

    def test_renamed_whisper_transcript_is_not_reprocessed(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            work_dir = Path(temporary_directory)
            course_dir = work_dir / "downloads" / "software-architecture"
            course_dir.mkdir(parents=True)
            transcript = course_dir / "Clase #1 - 2026-01-01.transcript.vtt"
            transcript.write_text(
                "WEBVTT\n\nNOTE\nTranscripción generada localmente con faster-whisper\n"
                "\n1\n00:00:00.000 --> 00:00:01.000\nHola\n",
                encoding="utf-8",
            )
            (work_dir / "recordings.json").write_text(
                json.dumps({
                    "software-architecture": {
                        "recordings": {
                            "recording-123": {
                                "url": "https://zoom.example/recording-123",
                                "organized_files": [transcript.name],
                            }
                        }
                    }
                }),
                encoding="utf-8",
            )

            result = transcribe_all(work_dir)

        self.assertEqual(result, (0, 0))

    def test_header_only_whisper_transcript_is_reprocessed(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            work_dir = Path(temporary_directory)
            course_dir = work_dir / "downloads" / "software-architecture"
            (course_dir / "transcripts" / "whisper").mkdir(parents=True)
            empty = course_dir / "transcripts" / "whisper" / "Clase #1 - 2026-01-01.whisper.transcript.vtt"
            empty.write_text(
                "WEBVTT\n\nNOTE\nTranscripción generada localmente con faster-whisper\n",
                encoding="utf-8",
            )
            (work_dir / "recordings.json").write_text(
                json.dumps({
                    "software-architecture": {
                        "recordings": {
                            "recording-123": {
                                "url": "https://zoom.example/recording-123",
                                "start_date": "2026-01-01T10:00:00Z",
                                "organized_files": [f"transcripts/whisper/{empty.name}"],
                            }
                        }
                    }
                }),
                encoding="utf-8",
            )
            (course_dir / "Clase [recording-123].mp4").write_bytes(b"video")
            faster_whisper = ModuleType("faster_whisper")
            faster_whisper.WhisperModel = Mock(return_value=Mock())

            def extract_audio_side_effect(source, remove_video=True):
                wav = source.with_suffix(".wav")
                wav.write_bytes(b"audio")
                return wav

            def transcribe_side_effect(_model, _wav, destination, _parts_dir, _settings=None):
                destination.write_text(
                    "WEBVTT\n\nNOTE\nTranscripción generada localmente con faster-whisper\n",
                    encoding="utf-8",
                )

            with (
                patch.dict("sys.modules", {"faster_whisper": faster_whisper}),
                patch("transcribe_missing.extract_audio", side_effect=extract_audio_side_effect),
                patch("transcribe_missing.transcribe", side_effect=transcribe_side_effect) as transcribe,
            ):
                result = transcribe_all(work_dir)

            self.assertEqual(result, (0, 1))
            self.assertTrue(transcribe.called)
            self.assertFalse(empty.exists())

    def test_zoom_transcript_retention_is_opt_in(self):
        from transcribe_missing import has_zoom_transcripts

        with tempfile.TemporaryDirectory() as temporary_directory:
            work_dir = Path(temporary_directory)
            course_dir = work_dir / "downloads" / "software-architecture" / "transcripts" / "zoom"
            course_dir.mkdir(parents=True)
            zoom_vtt = course_dir / "Clase #1.transcript.vtt"
            zoom_vtt.write_text("WEBVTT\n", encoding="utf-8")
            (work_dir / "recordings.json").write_text(
                json.dumps({
                    "software-architecture": {
                        "recordings": {
                            "recording-123": {
                                "url": "https://zoom.example/recording-123",
                                "organized_files": ["transcripts/zoom/Clase #1.transcript.vtt"],
                            }
                        }
                    }
                }),
                encoding="utf-8",
            )

            self.assertTrue(has_zoom_transcripts(work_dir))

    def test_class_filter_transcribes_only_selected_class(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            work_dir = Path(temporary_directory)
            course_dir = work_dir / "downloads" / "software-architecture"
            course_dir.mkdir(parents=True)
            (work_dir / "recordings.json").write_text(
                json.dumps({
                    "software-architecture": {
                        "recordings": {
                            "rec-1": {"url": "https://zoom.example/1", "start_date": "2026-01-01T10:00:00Z"},
                            "rec-2": {"url": "https://zoom.example/2", "start_date": "2026-01-02T10:00:00Z"},
                        }
                    }
                }),
                encoding="utf-8",
            )
            (course_dir / "Clase [rec-1].mp4").write_bytes(b"v")
            (course_dir / "Clase [rec-2].mp4").write_bytes(b"v")

            faster_whisper = ModuleType("faster_whisper")
            faster_whisper.WhisperModel = Mock(return_value=Mock())
            transcribed = []

            def extract_audio_side_effect(source, remove_video=True):
                wav = source.with_suffix(".wav")
                wav.write_bytes(b"audio")
                return wav

            def transcribe_side_effect(_model, _wav, destination, _parts_dir, _settings=None):
                transcribed.append(destination.name)
                destination.write_text(
                    "WEBVTT\n\nNOTE\nTranscripción generada localmente con faster-whisper\n"
                    "\n1\n00:00:00.000 --> 00:00:01.000\nHola\n",
                    encoding="utf-8",
                )

            with (
                patch.dict("sys.modules", {"faster_whisper": faster_whisper}),
                patch("transcribe_missing.extract_audio", side_effect=extract_audio_side_effect),
                patch("transcribe_missing.transcribe", side_effect=transcribe_side_effect),
            ):
                result = transcribe_all(work_dir, class_numbers=[2])

        self.assertEqual(result, (1, 0))
        self.assertTrue(any("Clase #2" in name for name in transcribed))
        self.assertFalse(any("Clase #1" in name for name in transcribed))


if __name__ == "__main__":
    unittest.main()
