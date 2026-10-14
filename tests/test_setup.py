import json
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

from claude_udea.setup import add_course, normalize_for_source, urls_alike


class SetupUrlTests(unittest.TestCase):
    def test_normalizes_ingenia_meeting_id(self):
        url, error = normalize_for_source("96660122811", "ingenia")

        self.assertIsNone(error)
        self.assertEqual(
            url,
            "https://ingenia.udea.edu.co/zoom/meeting/96660122811",
        )

    def test_rejects_ingenia_url_from_another_host(self):
        url, error = normalize_for_source(
            "https://example.com/zoom/meeting/96660122811",
            "ingenia",
        )

        self.assertIsNone(url)
        self.assertIsInstance(error, str)

    def test_accepts_supported_moodle_zoom_activity(self):
        url, error = normalize_for_source(
            "udearroba.udea.edu.co/mod/zoom/view.php?id=12345",
            "moodle",
        )

        self.assertIsNone(error)
        self.assertEqual(
            url,
            "https://udearroba.udea.edu.co/mod/zoom/view.php?id=12345",
        )

    def test_rejects_direct_zoom_recording_link_as_moodle_source(self):
        url, error = normalize_for_source(
            "https://udearroba.zoom.us/rec/play/abc",
            "moodle",
        )

        self.assertIsNone(url)
        self.assertIsNotNone(error)

    def test_detects_same_activity_with_tracking_query(self):
        self.assertTrue(urls_alike(
            "https://udearroba.udea.edu.co/mod/zoom/view.php?id=12345",
            "http://udearroba.udea.edu.co/mod/zoom/view.php?id=12345&utm_source=mail",
        ))

    def test_add_course_saves_ingenia_meeting(self):
        questionary = ModuleType("questionary")
        questionary.Style = Mock(return_value=None)
        questionary.Choice = Mock(side_effect=lambda title, value: value)
        questionary.select = Mock(return_value=SimpleNamespace(
            ask=Mock(return_value="ingenia")
        ))
        questionary.text = Mock(side_effect=[
            SimpleNamespace(ask=Mock(return_value="95990301433")),
            SimpleNamespace(ask=Mock(return_value="Arquitectura de Software II")),
        ])

        with tempfile.TemporaryDirectory() as temporary_directory:
            work_dir = Path(temporary_directory)
            config_path = work_dir / "config.json"
            config_path.write_text(json.dumps({"courses": {}}), encoding="utf-8")
            with patch.dict("sys.modules", {"questionary": questionary}):
                self.assertTrue(add_course(work_dir))

            config = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual(
            config["courses"]["arquitectura-de-software-ii"]["moodle_url"],
            "https://ingenia.udea.edu.co/zoom/meeting/95990301433",
        )
        self.assertEqual(
            config["courses"]["arquitectura-de-software-ii"]["source"],
            "ingenia",
        )


if __name__ == "__main__":
    unittest.main()