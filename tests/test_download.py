import json
import tempfile
import unittest
import uuid
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from claude_udea.download import (
    _build_rec_id_map,
    _class_category_for,
    _class_filename,
    _filename_suffix,
    _split_part,
    _recording_alias_ids,
    _recording_category,
    copy_transcripts,
    repair_course,
    rename_downloads,
)


class ClassNumberingTests(unittest.TestCase):
    def test_fabrica_escuela_and_architecture_have_independent_sequences(self):
        recordings = {
            "arquitectura-de-software": {
                "name": "Arquitectura de Software",
                "recordings": {
                    "arch-1": {
                        "title": "Arquitectura de Software",
                        "start_date": "2026-02-01T10:00:00Z",
                    },
                    "factory-1": {
                        "title": "Fábrica de Escuela",
                        "start_date": "2026-02-01T10:00:00Z",
                    },
                    "arch-2": {
                        "title": "Arquitectura de Software",
                        "start_date": "2026-02-08T10:00:00Z",
                    },
                    "factory-2": {
                        "title": "Fábrica de Escuela",
                        "start_date": "2026-02-08T10:00:00Z",
                    },
                },
            },
        }

        metadata = _build_rec_id_map(recordings)

        self.assertEqual(metadata["arch-1"]["class_number"], 1)
        self.assertEqual(metadata["factory-1"]["class_number"], 1)
        self.assertEqual(metadata["arch-2"]["class_number"], 2)
        self.assertEqual(metadata["factory-2"]["class_number"], 2)
        self.assertEqual(
            _class_filename(metadata["arch-1"], "2026-02-01"),
            "Clase #1 - 2026-02-01",
        )
        self.assertEqual(
            _class_filename(metadata["factory-1"], "2026-02-01"),
            "Fabrica Escuela - Clase #1 - 2026-02-01",
        )

    def test_recovers_legacy_long_organization_and_whisper_temps(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            download_dir = Path(temporary_directory)
            course_dir = download_dir / "comprension-lectora-felipe"
            course_dir.mkdir()
            intended_video = course_dir / "Clase #12 - 2026-09-02.mp4"
            temporary_video = course_dir / f".{intended_video.name}.{uuid.uuid4().hex}.tmp"
            temporary_video.write_bytes(b"video")

            intended_whisper = course_dir / "Clase #13 - 2026-09-04.whisper.transcript.vtt"
            temporary_whisper = intended_whisper.with_name(intended_whisper.name + ".tmp")
            temporary_whisper.write_text(
                "WEBVTT\n\nNOTE\nTranscripción generada localmente con faster-whisper\n",
                encoding="utf-8",
            )

            rename_downloads(download_dir, {})

            self.assertEqual(intended_video.read_bytes(), b"video")
            self.assertTrue(intended_whisper.is_file())
            self.assertFalse(temporary_video.exists())
            self.assertFalse(temporary_whisper.exists())

    def test_recordings_on_same_date_share_number_within_category(self):
        recordings = {
            "arquitectura-de-software": {
                "recordings": {
                    "arch-part-1": {
                        "title": "Arquitectura de Software",
                        "start_date": "2026-02-01T10:00:00Z",
                    },
                    "arch-part-2": {
                        "title": "Arquitectura de Software, continuación",
                        "start_date": "2026-02-01T10:00:00Z",
                    },
                    "factory": {
                        "title": "Fábrica de Escuela",
                        "start_date": "2026-02-01T10:00:00Z",
                    },
                },
            },
        }

        metadata = _build_rec_id_map(recordings)

        self.assertEqual(metadata["arch-part-1"]["class_number"], 1)
        self.assertEqual(metadata["arch-part-2"]["class_number"], 1)
        self.assertEqual(metadata["factory"]["class_number"], 1)

    def test_organizing_legacy_class_names_keeps_categories_distinct(self):
        recordings = {
            "arquitectura-de-software": {
                "name": "Arquitectura de Software",
                "recordings": {
                    "arch-1": {
                        "title": "Arquitectura de Software",
                        "start_date": "2026-02-01T10:00:00Z",
                    },
                    "factory-1": {
                        "title": "Fábrica de Escuela",
                        "start_date": "2026-02-01T10:00:00Z",
                    },
                },
            },
        }

        with tempfile.TemporaryDirectory() as temporary_directory:
            download_dir = Path(temporary_directory) / "downloads"
            course_dir = download_dir / "arquitectura-de-software"
            zoom_dir = course_dir / "transcripts" / "zoom"
            whisper_dir = course_dir / "transcripts" / "whisper"
            zoom_dir.mkdir(parents=True)
            whisper_dir.mkdir(parents=True)
            (zoom_dir / "Clase #1 - 2026-02-01.transcript.vtt").write_text(
                "WEBVTT\n\nArquitectura\n",
                encoding="utf-8",
            )
            (whisper_dir / "Clase #1 - 2026-02-01.whisper.transcript.vtt").write_text(
                "WEBVTT\n\nArquitectura Whisper\n",
                encoding="utf-8",
            )
            (course_dir / "Fabrica Escuela - Clase #1 - 2026-02-01.transcript.vtt").write_text(
                "WEBVTT\n\nFabrica\n",
                encoding="utf-8",
            )

            copy_transcripts(download_dir, recordings)
            index = json.loads(
                (download_dir / "transcripts" / "index.json").read_text(encoding="utf-8")
            )

        topics_by_file = {
            entry["file"]: entry["topic"]
            for entry in index["arquitectura-de-software"]["files"]
        }
        self.assertEqual(
            topics_by_file["Clase #1 - 2026-02-01.transcript.vtt"],
            "Arquitectura de Software",
        )
        self.assertEqual(
            topics_by_file["Fabrica Escuela - Clase #1 - 2026-02-01.transcript.vtt"],
            "Fábrica de Escuela",
        )
        sources_by_file = {
            entry["file"]: entry["source"]
            for entry in index["arquitectura-de-software"]["files"]
        }
        self.assertEqual(sources_by_file["Clase #1 - 2026-02-01.transcript.vtt"], "zoom")
        self.assertEqual(
            sources_by_file["Clase #1 - 2026-02-01.whisper.transcript.vtt"],
            "faster-whisper",
        )

    def test_recategorizes_recording_assets_without_changing_class_names(self):
        recordings = {
            "arquitectura-de-software": {
                "name": "Arquitectura de Software",
                "recordings": {
                    "recording-1": {
                        "title": "Arquitectura de Software",
                        "start_date": "2026-02-01T10:00:00Z",
                    },
                },
            },
        }

        with tempfile.TemporaryDirectory() as temporary_directory:
            download_dir = Path(temporary_directory)
            course_dir = download_dir / "arquitectura-de-software"
            course_dir.mkdir()
            names = [
                "Architecture [recording-1].mp4",
                "Architecture [recording-1].transcript.vtt",
                "Architecture [recording-1].whisper.transcript.vtt",
            ]
            for name in names:
                (course_dir / name).write_text("WEBVTT\n" if name.endswith(".vtt") else "chat", encoding="utf-8")

            rename_downloads(download_dir, recordings)
            organized = {
                path.relative_to(course_dir).as_posix()
                for path in course_dir.rglob("*")
                if path.is_file()
            }

        self.assertIn("videos/Clase #1 - 2026-02-01.mp4", organized)
        self.assertIn("transcripts/zoom/Clase #1 - 2026-02-01.transcript.vtt", organized)
        self.assertIn(
            "transcripts/whisper/Clase #1 - 2026-02-01.whisper.transcript.vtt",
            organized,
        )

    def test_asset_category_classifier(self):
        self.assertEqual(_recording_category("Clase [id].mp4", ".mp4"), "videos")
        self.assertEqual(_recording_category("Clase [id].transcript.vtt", ".transcript.vtt"), "transcripts/zoom")
        self.assertEqual(_recording_category("Clase [id].whisper.transcript.vtt", ".whisper.transcript.vtt"), "transcripts/whisper")
        self.assertEqual(_recording_category("Clase [id].chat.txt", ".chat.txt"), "")

    def test_migrates_older_whisper_vtt_by_its_note_marker(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            legacy_vtt = Path(temporary_directory) / "Clase [id].transcript.vtt"
            legacy_vtt.write_text(
                "WEBVTT\n\nNOTE\nTranscripción generada localmente con faster-whisper\n",
                encoding="utf-8",
            )

            self.assertEqual(
                _recording_category(legacy_vtt.name, ".transcript.vtt", legacy_vtt),
                "transcripts/whisper",
            )


class LooseFileOrganizationTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.download_dir = Path(self._temporary.name)
        self.course_dir = self.download_dir / "arquitectura-de-software"
        self.course_dir.mkdir()
        self.recordings = {
            "arquitectura-de-software": {
                "name": "Arquitectura de Software",
                "recordings": {
                    "factory-3": {
                        "title": "FABRICA DE ESCUELA INGENIERÍA DE SISTEMA (2026-2)",
                        "start_date": "2026-08-26T10:59:13Z",
                        "downloaded": True,
                    },
                },
            },
        }

    def tearDown(self):
        self._temporary.cleanup()

    def test_loose_factory_files_without_id_go_to_their_category_with_standard_name(self):
        loose_video = self.course_dir / "Fabrica Escuela - Clase #1 - 2026-08-26.mp4"
        loose_video.write_bytes(b"video")
        loose_vtt = self.course_dir / "Fabrica Escuela - Clase #1 - 2026-08-26.transcript.vtt"
        loose_vtt.write_text("WEBVTT\n", encoding="utf-8")

        rename_downloads(self.download_dir, self.recordings)

        self.assertTrue((self.course_dir / "videos" / "Fabrica Escuela - Clase #1 - 2026-08-26.mp4").is_file())
        self.assertTrue(
            (self.course_dir / "transcripts" / "zoom" / "Fabrica Escuela - Clase #1 - 2026-08-26.transcript.vtt").is_file()
        )
        self.assertFalse(loose_video.exists())
        self.assertFalse(loose_vtt.exists())

    def test_partial_and_temporary_downloads_are_kept_out_of_videos(self):
        partial = self.course_dir / "Clase #4 - 2026-09-05.mp4.part"
        partial.write_bytes(b"partial")
        legacy_temp = self.course_dir / "Clase #6 - 2026-09-12.mp4.3223.tmp.f1f7.tmp"
        legacy_temp.write_bytes(b"partial")

        rename_downloads(self.download_dir, self.recordings)

        self.assertTrue((self.course_dir / "incompletos" / partial.name).is_file())
        self.assertTrue((self.course_dir / "incompletos" / legacy_temp.name).is_file())
        self.assertEqual(list((self.course_dir / "videos").glob("*.part")), [])

    def test_unresolvable_root_files_are_swept_to_sin_clasificar(self):
        orphan = self.course_dir / "clase #17 - sin-fecha - chapter.vtt"
        orphan.write_text("WEBVTT\n", encoding="utf-8")

        rename_downloads(self.download_dir, self.recordings)

        self.assertFalse(orphan.exists())
        self.assertTrue(
            (self.course_dir / "transcripts" / "zoom" / orphan.name).is_file()
        )

    def test_file_with_id_and_no_recording_is_swept_not_left_in_root(self):
        stray = self.course_dir / "Algo [unknown-id].mp4"
        stray.write_bytes(b"video")

        rename_downloads(self.download_dir, self.recordings)

        self.assertFalse(stray.exists())
        self.assertTrue((self.course_dir / "sin-clasificar" / stray.name).is_file())

class RecordingsStoreTests(unittest.TestCase):
    def test_load_keeps_recordings_that_share_a_start_date(self):
        from claude_udea.cli import load_recordings

        data = {
            "arquitectura-de-software": {
                "name": "Arquitectura de Software",
                "recordings": {
                    "class-1": {"title": "Arquitectura de Software", "start_date": "2026-09-01T17:01:34Z"},
                    "factory-1": {"title": "FABRICA DE ESCUELA", "start_date": "2026-09-01T17:01:34Z"},
                },
            },
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "recordings.json"
            path.write_text(json.dumps(data), encoding="utf-8")

            loaded = load_recordings(path)

        self.assertEqual(set(loaded["arquitectura-de-software"]["recordings"]), {"class-1", "factory-1"})


class FilenameSuffixTests(unittest.TestCase):
    def test_extracts_suffix_after_rec_id_bracket(self):
        self.assertEqual(
            _filename_suffix("Clase [rec123].mp4", "rec123"),
            ".mp4",
        )
        self.assertEqual(
            _filename_suffix("Titulo [recording-1].transcript.vtt", "recording-1"),
            ".transcript.vtt",
        )

    def test_extracts_suffix_after_rec_id_with_copy_tag(self):
        self.assertEqual(
            _filename_suffix(
                "Clase #1 - 2026-09-01 [rec123 copy 2].mp4", "rec123"
            ),
            ".mp4",
        )
        self.assertEqual(
            _filename_suffix(
                "Fabrica Escuela - Clase #1 - 2026-08-26 [factory-3 copy 2].whisper.transcript.vtt",
                "factory-3",
            ),
            ".whisper.transcript.vtt",
        )

    def test_extracts_suffix_from_clean_filename_without_brackets(self):
        self.assertEqual(
            _filename_suffix("Clase #1 - 2026-02-01.mp4", ""),
            ".mp4",
        )
        self.assertEqual(
            _filename_suffix("Clase #1 - 2026-02-01.transcript.vtt", ""),
            ".transcript.vtt",
        )

    def test_part_markers_are_not_part_of_the_suffix(self):
        filename = "Clase #15 - 2026-09-29 - Parte 1 - Parte 2.cc.vtt"
        self.assertEqual(_filename_suffix(filename, ""), ".cc.vtt")
        self.assertEqual(
            _split_part(filename),
            ("Clase #15 - 2026-09-29", (1, 2), ".cc.vtt"),
        )


class CleanupLegacyNamesTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.download_dir = Path(self._temporary.name)
        self.course_dir = self.download_dir / "arquitectura-de-software"
        self.course_dir.mkdir(parents=True)

    def tearDown(self):
        self._temporary.cleanup()

    def _recordings(self, rec_id, title, start_date, organized_files=None):
        return {
            "arquitectura-de-software": {
                "name": "Arquitectura de Software",
                "recordings": {
                    rec_id: {
                        "title": title,
                        "start_date": start_date,
                        "organized_files": organized_files or [],
                    },
                },
            },
        }

    def test_removes_simple_rec_id_tag(self):
        legacy = self.course_dir / "Clase #1 - 2026-09-01 [rec123].mp4"
        legacy.write_bytes(b"video")
        recordings = self._recordings(
            "rec123", "Arquitectura de Software", "2026-09-01T10:00:00Z"
        )

        rename_downloads(self.download_dir, recordings)

        self.assertFalse(legacy.exists())
        self.assertTrue(
            (self.course_dir / "videos" / "Clase #1 - 2026-09-01.mp4").is_file()
        )

    def test_removes_copy_tag(self):
        legacy = self.course_dir / "Clase #1 - 2026-09-01 [rec123 copy 2].mp4"
        legacy.write_bytes(b"video")
        recordings = self._recordings(
            "rec123", "Arquitectura de Software", "2026-09-01T10:00:00Z"
        )

        rename_downloads(self.download_dir, recordings)

        self.assertFalse(legacy.exists())
        self.assertTrue(
            (self.course_dir / "videos" / "Clase #1 - 2026-09-01.mp4").is_file()
        )

    def test_handles_fabrica_escuela_prefix(self):
        legacy = (
            self.course_dir
            / "Fabrica Escuela - Clase #1 - 2026-08-26 [factory-3 copy 2].transcript.vtt"
        )
        legacy.write_text("WEBVTT\n", encoding="utf-8")
        recordings = self._recordings(
            "factory-3", "FABRICA DE ESCUELA INGENIERÍA DE SISTEMA", "2026-08-26T10:59:13Z"
        )

        rename_downloads(self.download_dir, recordings)

        self.assertFalse(legacy.exists())
        self.assertTrue(
            (
                self.course_dir
                / "transcripts" / "zoom"
                / "Fabrica Escuela - Clase #1 - 2026-08-26.transcript.vtt"
            ).is_file()
        )

    def test_avoids_collision_when_clean_name_exists(self):
        clean = self.course_dir / "videos" / "Clase #1 - 2026-09-01.mp4"
        clean.parent.mkdir(parents=True)
        clean.write_bytes(b"original")
        legacy = self.course_dir / "Clase #1 - 2026-09-01 [rec123 copy 2].mp4"
        legacy.write_bytes(b"duplicate")
        recordings = self._recordings(
            "rec123",
            "Arquitectura de Software",
            "2026-09-01T10:00:00Z",
            organized_files=["videos/Clase #1 - 2026-09-01.mp4"],
        )

        rename_downloads(self.download_dir, recordings)

        self.assertTrue(clean.is_file())
        self.assertEqual(clean.read_bytes(), b"original")
        self.assertFalse(legacy.exists())
        self.assertTrue(
            (self.course_dir / "videos" / "Clase #1 - 2026-09-01 - Parte 1.mp4").is_file()
        )

    def test_skips_files_without_legacy_tags(self):
        clean = self.course_dir / "videos" / "Clase #1 - 2026-09-01.mp4"
        clean.parent.mkdir(parents=True)
        clean.write_bytes(b"video")
        recordings = self._recordings(
            "rec123",
            "Arquitectura de Software",
            "2026-09-01T10:00:00Z",
            organized_files=["videos/Clase #1 - 2026-09-01.mp4"],
        )

        rename_downloads(self.download_dir, recordings)

        self.assertTrue(clean.is_file())
        self.assertEqual(clean.read_bytes(), b"video")


class DuplicateTagFormatTests(unittest.TestCase):
    def test_rename_downloads_labels_distinct_duplicates_as_parts(self):
        recordings = {
            "arquitectura-de-software": {
                "name": "Arquitectura de Software",
                "recordings": {
                    "recording-1": {
                        "title": "Arquitectura de Software",
                        "start_date": "2026-09-01T10:00:00Z",
                    },
                },
            },
        }

        with tempfile.TemporaryDirectory() as temporary_directory:
            download_dir = Path(temporary_directory)
            course_dir = download_dir / "arquitectura-de-software"
            videos_dir = course_dir / "videos"
            videos_dir.mkdir(parents=True)

            (videos_dir / "Clase #1 - 2026-09-01.mp4").write_bytes(b"first")
            duplicate = course_dir / "Duplicado [recording-1].mp4"
            duplicate.write_bytes(b"second")

            rename_downloads(download_dir, recordings)

            organized = sorted(
                path.relative_to(course_dir).as_posix()
                for path in course_dir.rglob("*")
                if path.is_file()
            )

            self.assertIn("videos/Clase #1 - 2026-09-01.mp4", organized)
            self.assertIn("videos/Clase #1 - 2026-09-01 - Parte 1.mp4", organized)
            self.assertFalse(duplicate.exists())

    def test_rename_downloads_preserves_cleanly_named_files_on_rerun(self):
        recordings = {
            "arquitectura-de-software": {
                "name": "Arquitectura de Software",
                "recordings": {
                    "recording-1": {
                        "title": "Arquitectura de Software",
                        "start_date": "2026-09-01T10:00:00Z",
                    },
                },
            },
        }

        with tempfile.TemporaryDirectory() as temporary_directory:
            download_dir = Path(temporary_directory)
            course_dir = download_dir / "arquitectura-de-software"
            videos_dir = course_dir / "videos"
            videos_dir.mkdir(parents=True)

            video_path = videos_dir / "Clase #1 - 2026-09-01.mp4"
            video_path.write_bytes(b"video")

            recordings["arquitectura-de-software"]["recordings"]["recording-1"][
                "organized_files"
            ] = ["videos/Clase #1 - 2026-09-01.mp4"]

            rename_downloads(download_dir, recordings)

            self.assertTrue(video_path.is_file())
            self.assertEqual(video_path.read_bytes(), b"video")

            videos = list(videos_dir.iterdir())
            self.assertEqual(len(videos), 1)
            self.assertEqual(videos[0].name, "Clase #1 - 2026-09-01.mp4")


class VideoDuplicateSafetyTests(unittest.TestCase):
    def test_backups_only_byte_identical_video_and_keeps_distinct_content_as_part(self):
        recordings = {
            "arquitectura-de-software": {
                "recordings": {
                    "rec-1": {
                        "title": "Arquitectura de Software",
                        "start_date": "2026-09-01T10:00:00Z",
                    },
                },
            },
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            download_dir = Path(temporary_directory)
            course_dir = download_dir / "arquitectura-de-software"
            videos = course_dir / "videos"
            videos.mkdir(parents=True)
            (videos / "Clase #1 - 2026-09-01.mp4").write_bytes(b"same")
            duplicate = course_dir / "Clase #1 - 2026-09-01 [rec-1 copy 2].mp4"
            duplicate.write_bytes(b"same")
            distinct = course_dir / "Clase #1 - 2026-09-01 [rec-1 copy 3].mp4"
            distinct.write_bytes(b"part two")
            recordings["arquitectura-de-software"]["recordings"]["rec-1"][
                "organized_files"
            ] = [
                "videos/Clase #1 - 2026-09-01.mp4",
                duplicate.name,
                distinct.name,
            ]

            rename_downloads(download_dir, recordings)

            canonical = videos / "Clase #1 - 2026-09-01.mp4"
            part = videos / "Clase #1 - 2026-09-01 - Parte 1.mp4"
            backup = course_dir / ".claude-udea-backup" / "identical-videos" / duplicate.name
            self.assertEqual(canonical.read_bytes(), b"same")
            self.assertTrue(backup.is_file())
            self.assertEqual(part.read_bytes(), b"part two")
            self.assertIn("videos/Clase #1 - 2026-09-01 - Parte 1.mp4", recordings[
                "arquitectura-de-software"]["recordings"]["rec-1"]["organized_files"])


class RecordingMergeTests(unittest.TestCase):
    def test_keeps_distinct_recording_ids_with_same_date_and_category(self):
        from claude_udea.cli import _merge_scraped

        existing = {}
        config = {
            "download_dir": ".",
            "courses": {"architecture": {"name": "Architecture"}},
        }
        links = [
            {
                "url": f"https://zoom.example/rec/share/{rec_id}",
                "full_url": f"https://zoom.example/rec/share/{rec_id}",
                "text": "Architecture",
                "topic": "Architecture",
                "meeting_id": meeting_id,
                "start_date": start_date,
                "duration_minutes": 60,
            }
            for rec_id, meeting_id, start_date in (
                ("rec-1", "room-a", "2026-09-01T10:00:00Z"),
                ("rec-2", "room-b", "2026-09-01T15:00:00Z"),
            )
        ]

        pending = _merge_scraped(existing, config, "architecture", links)

        self.assertEqual(set(existing["architecture"]["recordings"]), {"rec-1", "rec-2"})
        self.assertEqual({item[1] for item in pending}, {"rec-1", "rec-2"})

    def test_same_date_without_meeting_id_collapses_to_one_session(self):
        from claude_udea.cli import _merge_scraped

        existing = {}
        config = {
            "download_dir": ".",
            "courses": {"architecture": {"name": "Architecture"}},
        }
        links = [
            {
                "url": f"https://zoom.example/rec/share/{rec_id}",
                "full_url": f"https://zoom.example/rec/share/{rec_id}",
                "text": "Architecture",
                "topic": "Architecture",
                "start_date": "2026-09-01T10:00:00Z",
                "duration_minutes": 60,
            }
            for rec_id in ("rec-1", "rec-2")
        ]

        _merge_scraped(existing, config, "architecture", links)

        self.assertEqual(len(existing["architecture"]["recordings"]), 1)

    def test_duplicate_id_in_one_scrape_is_queued_once(self):
        from claude_udea.cli import _merge_scraped

        existing = {}
        config = {"download_dir": ".", "courses": {"architecture": {"name": "Architecture"}}}
        link = {
            "url": "https://zoom.example/rec/share/rec-1",
            "full_url": "https://zoom.example/rec/share/rec-1",
            "text": "Architecture",
            "topic": "Architecture",
            "start_date": "2026-09-01T10:00:00Z",
            "duration_minutes": 60,
        }

        pending = _merge_scraped(existing, config, "architecture", [link, link])

        self.assertEqual(len(pending), 1)


if __name__ == "__main__":
    unittest.main()


class MeetingIdClassificationTests(unittest.TestCase):
    FABRICA_IDS = {"99021321325"}

    def test_fabrica_title_on_architecture_meeting_is_course(self):
        rec_info = {
            "title": "FABRICA DE ESCUELA INGENIERÍA DE SISTEMA (2026-2)",
            "meeting_id": "97100466870",
        }
        self.assertEqual(_class_category_for(rec_info, self.FABRICA_IDS), "course")

    def test_architecture_title_on_fabrica_meeting_is_fabrica(self):
        rec_info = {
            "title": "2554585-2 ARQUITECTURA DE SOFTWAR",
            "meeting_id": "99021321325",
        }
        self.assertEqual(_class_category_for(rec_info, self.FABRICA_IDS), "fabrica_escuela")

    def test_title_fallback_without_meeting_id(self):
        rec_info = {"title": "FABRICA DE ESCUELA INGENIERÍA DE SISTEMA (2026-2)"}
        self.assertEqual(_class_category_for(rec_info, self.FABRICA_IDS), "fabrica_escuela")

    def test_title_fallback_without_configured_ids(self):
        rec_info = {
            "title": "FABRICA DE ESCUELA INGENIERÍA DE SISTEMA (2026-2)",
            "meeting_id": "99021321325",
        }
        self.assertEqual(_class_category_for(rec_info, None), "fabrica_escuela")

    def test_august_videos_of_architecture_meeting_number_as_course(self):
        recordings = {
            "arquitectura-de-software": {
                "name": "Arquitectura de Software",
                "recordings": {
                    "aug-971": {
                        "title": "FABRICA DE ESCUELA INGENIERÍA DE SISTEMA (2026-2)",
                        "meeting_id": "97100466870",
                        "start_date": "2026-08-12T11:00:00Z",
                    },
                    "aug-990": {
                        "title": "FABRICA DE ESCUELA INGENIERÍA DE SISTEMA (2026-2)",
                        "meeting_id": "99021321325",
                        "start_date": "2026-08-12T11:00:00Z",
                    },
                    "sep-971": {
                        "title": "2554585-2 ARQUITECTURA DE SOFTWAR",
                        "meeting_id": "97100466870",
                        "start_date": "2026-09-10T17:00:00Z",
                    },
                },
            },
        }
        options = {
            "arquitectura-de-software": {"fabrica_meeting_ids": ["99021321325"]},
        }
        id_map = _build_rec_id_map(recordings, options)

        self.assertEqual(id_map["aug-971"]["class_category"], "course")
        self.assertEqual(id_map["aug-971"]["class_number"], 1)
        self.assertEqual(id_map["sep-971"]["class_number"], 2)
        self.assertEqual(id_map["aug-990"]["class_category"], "fabrica_escuela")
        self.assertEqual(id_map["aug-990"]["class_number"], 1)


class SessionDedupTests(unittest.TestCase):
    def _config(self):
        return {
            "download_dir": ".",
            "courses": {"architecture": {"name": "Architecture"}},
        }

    @staticmethod
    def _link(rec_id, meeting_id, start_date):
        return {
            "url": f"https://zoom.example/rec/share/{rec_id}",
            "full_url": f"https://zoom.example/rec/share/{rec_id}",
            "text": "Architecture",
            "topic": "Architecture",
            "meeting_id": meeting_id,
            "start_date": start_date,
            "duration_minutes": 60,
        }

    def test_same_meeting_and_date_collapse_into_one_recording(self):
        from claude_udea.cli import _merge_scraped

        existing = {}
        links = [
            self._link("rec-1", "97100466870", "2026-08-19T11:49:43Z"),
            self._link("rec-2", "97100466870", "2026-08-19T11:49:43Z"),
        ]

        pending = _merge_scraped(existing, self._config(), "architecture", links)

        recordings = existing["architecture"]["recordings"]
        self.assertEqual(len(recordings), 1)
        self.assertEqual({item[1] for item in pending}, set(recordings))

    def test_different_sessions_same_day_keep_both(self):
        from claude_udea.cli import _merge_scraped

        existing = {}
        links = [
            self._link("rec-1", "97100466870", "2026-09-16T11:06:05Z"),
            self._link("rec-2", "99021321325", "2026-09-16T18:06:05Z"),
        ]

        _merge_scraped(existing, self._config(), "architecture", links)

        self.assertEqual(len(existing["architecture"]["recordings"]), 2)

    def test_new_link_matching_existing_session_updates_it(self):
        from claude_udea.cli import _merge_scraped

        existing = {}
        first = [self._link("rec-1", "97100466870", "2026-08-19T11:49:43Z")]
        _merge_scraped(existing, self._config(), "architecture", first)

        # La misma sesión descubierta después con otra URL y mejor duración.
        second = [self._link("rec-9", "97100466870", "2026-08-19T11:49:43Z")]
        second[0]["duration_minutes"] = 72
        _merge_scraped(existing, self._config(), "architecture", second)

        recordings = existing["architecture"]["recordings"]
        self.assertEqual(set(recordings), {"rec-1"})
        self.assertEqual(recordings["rec-1"]["duration_minutes"], 72)

    def test_persisted_duplicates_are_collapsed_before_merge(self):
        from claude_udea.cli import _merge_scraped

        existing = {
            "architecture": {
                "name": "Architecture",
                "recordings": {
                    "rec-1": {
                        "url": "https://zoom.example/rec/share/rec-1",
                        "meeting_id": "97100466870",
                        "start_date": "2026-08-19T11:49:43Z",
                        "duration_minutes": 0,
                        "downloaded": True,
                        "organized_files": ["videos/Clase #1.mp4"],
                    },
                    "rec-2": {
                        "url": "https://zoom.example/rec/share/rec-2",
                        "meeting_id": "97100466870",
                        "start_date": "2026-08-19T11:49:43Z",
                        "duration_minutes": 72,
                        "downloaded": False,
                        "organized_files": ["transcripts/zoom/Clase #1.cc.vtt"],
                    },
                },
            },
        }

        _merge_scraped(existing, self._config(), "architecture", [])

        recordings = existing["architecture"]["recordings"]
        self.assertEqual(set(recordings), {"rec-1"})
        keeper = recordings["rec-1"]
        self.assertTrue(keeper["downloaded"])
        self.assertEqual(keeper["duration_minutes"], 72)
        self.assertIn("videos/Clase #1.mp4", keeper["organized_files"])
        self.assertIn("transcripts/zoom/Clase #1.cc.vtt", keeper["organized_files"])


class VideoArtifactBackupTests(unittest.TestCase):
    def _rec_info(self, organized_files):
        return {
            "title": "2554585-2 ARQUITECTURA DE SOFTWAR",
            "meeting_id": "97100466870",
            "start_date": "2026-08-12T11:03:50Z",
            "organized_files": organized_files,
        }

    def test_backup_copy_does_not_count_as_video_present(self):
        from claude_udea.cli import _has_video_artifact, _recording_video_missing

        with tempfile.TemporaryDirectory() as temporary_directory:
            course_dir = Path(temporary_directory) / "arquitectura-de-software"
            backup = course_dir / ".claude-udea-backup" / "identical-videos"
            backup.mkdir(parents=True)
            name = "Clase #1 - 2026-08-12.mp4"
            (backup / name).write_bytes(b"video")
            rec_info = self._rec_info([f".claude-udea-backup/identical-videos/{name}"])

            self.assertFalse(_has_video_artifact(course_dir, rec_info, "rec-1"))
            self.assertTrue(_recording_video_missing(course_dir, rec_info, "rec-1"))

    def test_organized_video_counts_as_present(self):
        from claude_udea.cli import _has_video_artifact

        with tempfile.TemporaryDirectory() as temporary_directory:
            course_dir = Path(temporary_directory) / "arquitectura-de-software"
            videos = course_dir / "videos"
            videos.mkdir(parents=True)
            name = "Clase #1 - 2026-08-12.mp4"
            (videos / name).write_bytes(b"video")
            rec_info = self._rec_info([f"videos/{name}"])

            self.assertTrue(_has_video_artifact(course_dir, rec_info, "rec-1"))


class RecordingAliasTests(unittest.TestCase):
    def test_alias_ids_include_key_and_url_token(self):
        rec_info = {
            "url": "https://zoom.example/rec/share/TOKEN123.ABC",
            "share_url": "https://zoom.example/rec/share/TOKEN123.ABC",
        }
        self.assertEqual(
            _recording_alias_ids("KEY1", rec_info), ["KEY1", "TOKEN123.ABC"]
        )

    def test_rename_downloads_matches_raw_file_by_url_token(self):
        recordings = {
            "arquitectura-de-software": {
                "recordings": {
                    "KEY1": {
                        "title": "2554585-2 ARQUITECTURA DE SOFTWAR",
                        "meeting_id": "97100466870",
                        "start_date": "2026-08-12T11:03:50Z",
                        "url": "https://zoom.example/rec/share/TOKEN123.ABC",
                        "share_url": "https://zoom.example/rec/share/TOKEN123.ABC",
                    },
                },
            },
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            download_dir = Path(temporary_directory)
            course_dir = download_dir / "arquitectura-de-software"
            course_dir.mkdir(parents=True)
            raw = course_dir / "2554585-2 ARQUITECTURA DE SOFTWAR [TOKEN123.ABC].mp4"
            raw.write_bytes(b"video")

            rename_downloads(download_dir, recordings)

            self.assertFalse(raw.exists())
            self.assertTrue((course_dir / "videos" / "Clase #1 - 2026-08-12.mp4").is_file())


class PartOrganizationTests(unittest.TestCase):
    def test_same_record_raw_duplicates_do_not_mark_url_suspect(self):
        recordings = RepairCourseTests._recordings("2026-09-01")
        rec = recordings["architecture"]["recordings"]["rec-1"]
        rec["url"] = "https://zoom.example/rec/share/rec-1"
        with tempfile.TemporaryDirectory() as temporary_directory:
            downloads = Path(temporary_directory)
            course_dir = downloads / "architecture"
            course_dir.mkdir()
            for name in ("First [rec-1].mp4", "Second [rec-1 copy 2].mp4"):
                (course_dir / name).write_bytes(b"same")
            rename_downloads(downloads, recordings)
            self.assertNotIn("suspect_url", rec)
            self.assertTrue((course_dir / "videos" / "Clase #1 - 2026-09-01.mp4").exists())

    def test_duplicate_video_caption_inherits_retained_part(self):
        recordings = RepairCourseTests._recordings("2026-09-01")
        with tempfile.TemporaryDirectory() as temporary_directory:
            downloads = Path(temporary_directory)
            course_dir = downloads / "architecture"
            videos = course_dir / "videos"
            videos.mkdir(parents=True)
            (videos / "Clase #1 - 2026-09-01.mp4").write_bytes(b"primary")
            (videos / "Clase #1 - 2026-09-01 - Parte 1.mp4").write_bytes(b"part")
            (course_dir / "Raw [rec-1].mp4").write_bytes(b"part")
            (course_dir / "Raw [rec-1].cc.vtt").write_bytes(b"WEBVTT\ncaption")
            rename_downloads(downloads, recordings)
            self.assertTrue((course_dir / "transcripts/zoom" / "Clase #1 - 2026-09-01 - Parte 1.cc.vtt").exists())
            self.assertFalse((course_dir / "transcripts/zoom" / "Clase #1 - 2026-09-01.cc.vtt").exists())

    def test_stale_paths_do_not_claim_other_class_assets(self):
        recordings = RepairCourseTests._recordings("2026-09-01", "2026-09-02")
        recs = recordings["architecture"]["recordings"]
        with tempfile.TemporaryDirectory() as temporary_directory:
            download_dir = Path(temporary_directory)
            course_dir = download_dir / "architecture"
            zoom = course_dir / "transcripts" / "zoom"
            videos = course_dir / "videos"
            zoom.mkdir(parents=True)
            videos.mkdir()
            names = ["videos/Clase #1 - 2026-09-01.mp4", "transcripts/zoom/Clase #1 - 2026-09-01.cc.vtt"]
            for name in names:
                (course_dir / name).write_bytes(b"original")
            recs["rec-2"]["organized_files"] = names
            rename_downloads(download_dir, recordings)
            for name in names:
                self.assertEqual((course_dir / name).read_bytes(), b"original")
            self.assertEqual(recs["rec-2"]["organized_files"], [])

    def test_video_and_zoom_transcripts_share_collision_part(self):
        recordings = {
            "architecture": {
                "recordings": {
                    rec_id: {
                        "title": "Architecture",
                        "start_date": "2026-09-01T10:00:00Z",
                        "url": f"https://zoom.example/rec/share/{rec_id}",
                    }
                    for rec_id in ("rec-a", "rec-b")
                },
            },
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            download_dir = Path(temporary_directory)
            course_dir = download_dir / "architecture"
            course_dir.mkdir()
            for rec_id, data in (("rec-a", b"a"), ("rec-b", b"b")):
                (course_dir / f"Architecture [{rec_id}].mp4").write_bytes(data)
                (course_dir / f"Architecture [{rec_id}].cc.vtt").write_text(
                    f"WEBVTT\n\n{rec_id}\n", encoding="utf-8",
                )

            rename_downloads(download_dir, recordings)

            videos = course_dir / "videos"
            zoom = course_dir / "transcripts" / "zoom"
            self.assertTrue((videos / "Clase #1 - 2026-09-01.mp4").is_file())
            self.assertTrue((videos / "Clase #1 - 2026-09-01 - Parte 1.mp4").is_file())
            self.assertTrue((zoom / "Clase #1 - 2026-09-01.cc.vtt").is_file())
            self.assertTrue((zoom / "Clase #1 - 2026-09-01 - Parte 1.cc.vtt").is_file())

    def test_subs_only_ignores_archive_and_skips_video(self):
        from claude_udea.download import download_one

        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            archive = output_dir / ".download-archive.txt"
            archive.write_text("zoom rec-1\n", encoding="utf-8")
            commands = []

            def run(command, **_kwargs):
                commands.append(command)
                (output_dir / "subtitles.cc.vtt").write_text("WEBVTT\n", encoding="utf-8")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch("claude_udea.download.subprocess.run", side_effect=run):
                status = download_one(
                    "https://zoom.example/rec/share/rec-1", output_dir, archive,
                    subs_only=True,
                )

            self.assertEqual(status, "ok")
            self.assertIn("--skip-download", commands[0])
            self.assertIn("--no-download-archive", commands[0])


class RepairCourseTests(unittest.TestCase):
    @patch("claude_udea.download._ffprobe_available", return_value=True)
    @patch("claude_udea.download._probe_video", return_value=(30, datetime(2026, 9, 1, 10)))
    def test_short_valid_video_is_preserved_and_stale_empty_flag_cleared(self, _probe, _available):
        recordings = self._recordings("2026-09-01")
        rec = recordings["architecture"]["recordings"]["rec-1"]
        rec["empty_recording"] = True
        with tempfile.TemporaryDirectory() as temporary_directory:
            course_dir = Path(temporary_directory) / "architecture"
            videos = course_dir / "videos"
            videos.mkdir(parents=True)
            source = videos / "Clase #1 - 2026-09-01.mp4"
            source.write_bytes(b"short-valid-video")
            repair_course(course_dir, recordings["architecture"], _build_rec_id_map(recordings))
            self.assertTrue(source.exists())
            self.assertNotIn("empty_recording", rec)

    @patch("claude_udea.download._ffprobe_available", return_value=True)
    @patch("claude_udea.download._probe_video", return_value=(None, None))
    def test_small_video_with_unknown_probe_and_zero_rounded_minutes_is_preserved(self, _probe, _available):
        recordings = self._recordings("2026-08-28")
        rec = recordings["architecture"]["recordings"]["rec-1"]
        rec["duration_minutes"] = 0
        with tempfile.TemporaryDirectory() as temporary_directory:
            course_dir = Path(temporary_directory) / "architecture"
            videos = course_dir / "videos"
            videos.mkdir(parents=True)
            source = videos / "Clase #1 - 2026-08-28.mp4"
            source.write_bytes(b"short media")

            repair_course(course_dir, recordings["architecture"], _build_rec_id_map(recordings))

            self.assertTrue(source.exists())
            self.assertNotIn("empty_recording", rec)

    @staticmethod
    def _recordings(*dates):
        return {
            "architecture": {
                "recordings": {
                    f"rec-{index}": {
                        "title": "Architecture",
                        "start_date": f"{date}T10:00:00Z",
                        "organized_files": [],
                    }
                    for index, date in enumerate(dates, start=1)
                },
            },
        }

    def test_dry_run_normalizes_repeated_part_without_moving_files(self):
        recordings = self._recordings("2026-09-01")
        with tempfile.TemporaryDirectory() as temporary_directory:
            course_dir = Path(temporary_directory) / "architecture"
            videos = course_dir / "videos"
            zoom = course_dir / "transcripts" / "zoom"
            videos.mkdir(parents=True)
            zoom.mkdir(parents=True)
            video = videos / "Clase #1 - 2026-09-01 - Parte 1 - Parte 1.mp4"
            caption = zoom / "Clase #1 - 2026-09-01 - Parte 1 - Parte 1.cc.vtt"
            video.write_bytes(b"x" * (1024 * 1024))
            caption.write_text("WEBVTT\n\ncaption\n", encoding="utf-8")

            report = repair_course(
                course_dir, recordings["architecture"], _build_rec_id_map(recordings),
                dry_run=True,
            )

            self.assertTrue(any(action[0] == "rename" for action in report["actions"]))
            self.assertTrue(video.exists())
            self.assertTrue(caption.exists())

    @patch("claude_udea.download._ffprobe_available", return_value=True)
    @patch("claude_udea.download._probe_video", return_value=(0, None))
    def test_applies_empty_video_backup_and_marks_recording(self, _probe, _available):
        recordings = self._recordings("2026-09-01")
        rec_info = recordings["architecture"]["recordings"]["rec-1"]
        with tempfile.TemporaryDirectory() as temporary_directory:
            course_dir = Path(temporary_directory) / "architecture"
            videos = course_dir / "videos"
            videos.mkdir(parents=True)
            empty = videos / "Clase #1 - 2026-09-01.mp4"
            empty.write_bytes(b"empty")

            report = repair_course(
                course_dir, recordings["architecture"], _build_rec_id_map(recordings),
            )

            self.assertTrue(report["actions"])
            self.assertTrue(rec_info["empty_recording"])
            self.assertFalse(empty.exists())
            self.assertTrue(
                (course_dir / ".claude-udea-backup" / "empty-videos" / empty.name).is_file()
            )
            manifest = course_dir / ".claude-udea-backup" / "empty-videos" / "manifest.jsonl"
            self.assertTrue(manifest.is_file())

    @patch("claude_udea.download._ffprobe_available", return_value=True)
    @patch("claude_udea.download._probe_video", return_value=(3600, datetime(2026, 9, 1, 10)))
    def test_verified_duplicate_video_keeps_owner_and_repair_is_idempotent(self, _probe, _available):
        recordings = self._recordings("2026-09-01", "2026-09-02")
        with tempfile.TemporaryDirectory() as temporary_directory:
            course_dir = Path(temporary_directory) / "architecture"
            videos = course_dir / "videos"
            videos.mkdir(parents=True)
            owner = videos / "Clase #1 - 2026-09-01.mp4"
            duplicate = videos / "Clase #2 - 2026-09-02.mp4"
            owner.write_bytes(b"x" * (1024 * 1024))
            duplicate.write_bytes(owner.read_bytes())
            meta = _build_rec_id_map(recordings)
            repair_course(course_dir, recordings["architecture"], meta)
            self.assertTrue(owner.exists())
            self.assertFalse(duplicate.exists())
            second = repair_course(course_dir, recordings["architecture"], meta)
            self.assertEqual(second["actions"], [])

    @patch("claude_udea.download._ffprobe_available", return_value=False)
    def test_orphan_chapter_is_backed_up_but_primary_chapter_survives(self, _available):
        recordings = self._recordings("2026-09-01")
        with tempfile.TemporaryDirectory() as temporary_directory:
            course_dir = Path(temporary_directory) / "architecture"
            zoom = course_dir / "transcripts" / "zoom"
            zoom.mkdir(parents=True)
            primary = zoom / "Clase #1 - 2026-09-01.chapter.vtt"
            orphan = zoom / "Clase #1 - 2026-09-01 - Parte 3.chapter.vtt"
            primary.write_bytes(b"WEBVTT\n")
            orphan.write_bytes(b"WEBVTT\n")
            repair_course(course_dir, recordings["architecture"], _build_rec_id_map(recordings))
            self.assertTrue(primary.exists())
            self.assertFalse(orphan.exists())
            self.assertTrue((course_dir / ".claude-udea-backup" / "orphan-transcripts" / orphan.name).exists())

    def test_central_index_preserves_part_and_zoom_variant(self):
        recordings = self._recordings("2026-09-01")
        with tempfile.TemporaryDirectory() as temporary_directory:
            download_dir = Path(temporary_directory)
            zoom = download_dir / "architecture" / "transcripts" / "zoom"
            zoom.mkdir(parents=True)
            name = "Clase #1 - 2026-09-01 - Parte 2.cc.vtt"
            (zoom / name).write_text("WEBVTT\n\ncaption\n", encoding="utf-8")
            copy_transcripts(download_dir, recordings)
            index = json.loads((download_dir / "transcripts" / "index.json").read_text(encoding="utf-8"))
            entry = index["architecture"]["files"][0]
            self.assertEqual(entry["file"], name)
            self.assertEqual(entry["part"], 2)
            self.assertEqual(entry["source"], "zoom")
            self.assertEqual(entry["type"], "cc")

    def test_course_scoped_copy_preserves_other_course_and_index(self):
        recordings = self._recordings("2026-09-01")
        with tempfile.TemporaryDirectory() as temporary_directory:
            downloads = Path(temporary_directory)
            central = downloads / "transcripts"
            other = central / "other"
            other.mkdir(parents=True)
            kept = other / "existing.vtt"
            kept.write_bytes(b"untouched")
            other_index = {"course_name": "Other", "files": [{"file": "existing.vtt"}]}
            (central / "index.json").write_text(json.dumps({"other": other_index}), encoding="utf-8")
            zoom = downloads / "architecture" / "transcripts/zoom"
            zoom.mkdir(parents=True)
            (zoom / "Clase #1 - 2026-09-01.cc.vtt").write_bytes(b"WEBVTT\n")
            copy_transcripts(downloads, recordings, course_slugs=["architecture"])
            self.assertEqual(kept.read_bytes(), b"untouched")
            index = json.loads((central / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(index["other"], other_index)

    @patch("claude_udea.download._ffprobe_available", return_value=False)
    def test_distinct_legacy_part_spellings_never_overwrite_content(self, _available):
        recordings = self._recordings("2026-09-01")
        recordings["architecture"]["recordings"]["rec-1"]["duration_minutes"] = 60
        with tempfile.TemporaryDirectory() as temporary_directory:
            course_dir = Path(temporary_directory) / "architecture"
            videos = course_dir / "videos"
            videos.mkdir(parents=True)
            (videos / "Clase #1 - 2026-09-01 - Parte 1.mp4").write_bytes(b"first")
            (videos / "Clase #1 - 2026-09-01 (1).mp4").write_bytes(b"second")
            repair_course(course_dir, recordings["architecture"], _build_rec_id_map(recordings))
            self.assertEqual({path.read_bytes() for path in videos.glob("*.mp4")}, {b"first", b"second"})

    def test_repair_command_dry_run_does_not_write_or_download(self):
        from claude_udea.cli import repair_videos_command

        recordings = self._recordings("2026-09-01")
        with tempfile.TemporaryDirectory() as temporary_directory:
            work_dir = Path(temporary_directory)
            recordings_path = work_dir / "recordings.json"
            recordings_path.write_text(json.dumps(recordings), encoding="utf-8")
            before = recordings_path.read_bytes()
            course_dir = work_dir / "downloads" / "architecture"
            videos = course_dir / "videos"
            videos.mkdir(parents=True)
            source = videos / "Clase #1 - 2026-09-01.mp4"
            source.write_bytes(b"empty")
            config = {
                "download_dir": str(work_dir / "downloads"),
                "recordings_file": str(recordings_path),
                "courses": {"architecture": {}},
            }
            with patch("claude_udea.download.download_one") as download:
                repair_videos_command(config, ["architecture"], dry_run=True)
                download.assert_not_called()
            self.assertEqual(recordings_path.read_bytes(), before)
            self.assertEqual(source.read_bytes(), b"empty")
            self.assertFalse((course_dir / ".claude-udea-backup").exists())

    @patch("claude_udea.download._ffprobe_available", return_value=True)
    @patch("claude_udea.download._probe_video", return_value=(3600, datetime(2026, 9, 2, 10)))
    def test_reassignment_updates_owner_and_quarantines_unproven_caption(self, _probe, _available):
        recordings = self._recordings("2026-09-01", "2026-09-02")
        recs = recordings["architecture"]["recordings"]
        with tempfile.TemporaryDirectory() as temporary_directory:
            course_dir = Path(temporary_directory) / "architecture"
            videos = course_dir / "videos"
            zoom = course_dir / "transcripts/zoom"
            videos.mkdir(parents=True)
            zoom.mkdir(parents=True)
            old = "videos/Clase #1 - 2026-09-01.mp4"
            new = "videos/Clase #2 - 2026-09-02.mp4"
            (course_dir / old).write_bytes(b"x" * (1024 * 1024))
            recs["rec-1"]["organized_files"] = [old]
            caption = zoom / "Clase #1 - 2026-09-01.cc.vtt"
            caption.write_bytes(b"WEBVTT\nuncertain caption")
            repair_course(course_dir, recordings["architecture"], _build_rec_id_map(recordings))
            self.assertNotIn(new, recs["rec-1"]["organized_files"])
            self.assertIn(new, recs["rec-2"]["organized_files"])
            self.assertFalse(caption.exists())
            self.assertFalse((zoom / "Clase #2 - 2026-09-02.cc.vtt").exists())
            self.assertTrue(recs["rec-2"]["zoom_subs_missing"])

    def test_whisper_and_chapter_do_not_count_as_zoom_speech_subtitles(self):
        from claude_udea.cli import _recording_subs_present

        rec_info = self._recordings("2026-09-01")["architecture"]["recordings"]["rec-1"]
        with tempfile.TemporaryDirectory() as temporary_directory:
            course_dir = Path(temporary_directory)
            for suffix in (".chapter.vtt", ".whisper.transcript.vtt"):
                path = course_dir / f"Clase #1 - 2026-09-01{suffix}"
                path.write_bytes(b"WEBVTT\n")
            self.assertFalse(_recording_subs_present(course_dir, rec_info))
            (course_dir / "Clase #1 - 2026-09-01.cc.vtt").write_bytes(b"WEBVTT\n")
            self.assertTrue(_recording_subs_present(course_dir, rec_info))

    @patch("claude_udea.download._ffprobe_available", return_value=False)
    def test_lone_part_transcript_is_not_promoted_to_primary(self, _available):
        recordings = self._recordings("2026-09-01")
        with tempfile.TemporaryDirectory() as temporary_directory:
            course_dir = Path(temporary_directory) / "architecture"
            zoom = course_dir / "transcripts" / "zoom"
            zoom.mkdir(parents=True)
            source = zoom / "Clase #1 - 2026-09-01 - Parte 2.cc.vtt"
            source.write_bytes(b"WEBVTT\n")
            repair_course(course_dir, recordings["architecture"], _build_rec_id_map(recordings))
            self.assertFalse(source.exists())
            self.assertFalse((zoom / "Clase #1 - 2026-09-01.cc.vtt").exists())

    @patch("claude_udea.download._ffprobe_available", return_value=False)
    def test_rebase_collision_preserves_video_caption_pair(self, _available):
        recordings = self._recordings("2026-09-01")
        recordings["architecture"]["recordings"]["rec-1"]["duration_minutes"] = 60
        with tempfile.TemporaryDirectory() as temporary_directory:
            course_dir = Path(temporary_directory) / "architecture"
            for category, suffix in (("videos", ".mp4"), ("transcripts/zoom", ".cc.vtt")):
                folder = course_dir / category
                folder.mkdir(parents=True)
                (folder / f"Clase #1 - 2026-09-01{suffix}").write_bytes(b"first")
                (folder / f"Clase #9 - 2026-09-01{suffix}").write_bytes(b"second")
            repair_course(course_dir, recordings["architecture"], _build_rec_id_map(recordings))
            self.assertTrue((course_dir / "videos" / "Clase #1 - 2026-09-01 - Parte 1.mp4").exists())
            self.assertTrue((course_dir / "transcripts/zoom" / "Clase #1 - 2026-09-01 - Parte 1.cc.vtt").exists())

    def test_duplicate_zoom_subtitles_are_backed_up_and_flagged_for_refetch(self):
        recordings = self._recordings("2026-09-01", "2026-09-02")
        recs = recordings["architecture"]["recordings"]
        with tempfile.TemporaryDirectory() as temporary_directory:
            course_dir = Path(temporary_directory) / "architecture"
            zoom = course_dir / "transcripts" / "zoom"
            zoom.mkdir(parents=True)
            first = zoom / "Clase #1 - 2026-09-01.cc.vtt"
            second = zoom / "Clase #2 - 2026-09-02.cc.vtt"
            first.write_text("WEBVTT\n\nsame captions\n", encoding="utf-8")
            second.write_text("WEBVTT\n\nsame captions\n", encoding="utf-8")

            report = repair_course(
                course_dir, recordings["architecture"], _build_rec_id_map(recordings),
            )

            self.assertTrue(report["flags"]["rec-1"]["zoom_subs_missing"])
            self.assertTrue(report["flags"]["rec-2"]["zoom_subs_missing"])
            self.assertFalse(first.exists())
            self.assertFalse(second.exists())
            self.assertEqual(len(list((course_dir / ".claude-udea-backup" / "misassigned-transcripts").glob("*.vtt"))), 2)


if __name__ == "__main__":
    unittest.main()
