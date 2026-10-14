import unittest
from unittest.mock import Mock
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from bs4 import BeautifulSoup

from claude_udea.materials import (
    _course_entries,
    _is_safe_pluginfile,
    _page_text,
    _course_section_urls,
    discover_course_url,
    scrape_course_materials,
)


class MoodleMaterialsTests(unittest.TestCase):
    def test_discovers_course_id_from_activity_breadcrumb(self):
        response = Mock()
        response.url = "https://udearroba.udea.edu.co/internos/mod/recordingszoom/recordinglist.php?id=2760135"
        response.text = '<a href="/internos/course/view.php?id=26422">Curso</a>'
        response.raise_for_status.return_value = None
        session = Mock()
        session.get.return_value = response

        course_url = discover_course_url(
            session,
            {
                "name": "Modelos y Simulación",
                "moodle_url": response.url,
            },
        )

        self.assertEqual(
            course_url,
            "https://udearroba.udea.edu.co/internos/course/view.php?id=26422",
        )

    def test_course_page_collects_supported_modules_and_public_files(self):
        soup = BeautifulSoup(
            """
            <main>
              <a href="/internos/pluginfile.php/4/mod_label/intro/plan.pdf">Plan</a>
              <a href="/internos/mod/resource/view.php?id=10">Guía</a>
              <a href="/internos/mod/folder/view.php?id=11">Lecturas</a>
              <a href="/internos/mod/page/view.php?id=12">Unidad</a>
              <a href="/internos/mod/url/view.php?id=13">Enlace</a>
              <a href="/internos/mod/assign/view.php?id=14">Tarea</a>
              <a href="/internos/mod/quiz/view.php?id=15">Parcial</a>
            </main>
            """,
            "html.parser",
        )

        entries = _course_entries(soup, "https://udearroba.udea.edu.co/internos/course/view.php?id=3", "udearroba.udea.edu.co")

        self.assertEqual(
            [entry["kind"] for entry in entries],
            ["file", "resource", "folder", "page", "url", "assign"],
        )

    def test_discovers_all_section_pages_for_the_same_course(self):
        soup = BeautifulSoup(
            """
            <a href="/internos/course/view.php?id=26363&section=0">General</a>
            <a href="/internos/course/view.php?id=26363&section=1">Unidad 1</a>
            <a href="/internos/course/view.php?id=26363&section=5">Unidad 5</a>
            <a href="/internos/course/view.php?id=99999&section=1">Otro curso</a>
            <a href="/internos/course/view.php?id=26363">Vista del curso</a>
            """,
            "html.parser",
        )

        sections = _course_section_urls(
            soup,
            "https://udearroba.udea.edu.co/internos/course/view.php?id=26363",
            "udearroba.udea.edu.co",
            "26363",
        )

        self.assertEqual(
            sections,
            [
                "https://udearroba.udea.edu.co/internos/course/view.php?id=26363&section=0",
                "https://udearroba.udea.edu.co/internos/course/view.php?id=26363&section=1",
                "https://udearroba.udea.edu.co/internos/course/view.php?id=26363&section=5",
            ],
        )

    def test_private_student_submissions_are_never_downloadable(self):
        self.assertFalse(_is_safe_pluginfile(
            "https://udearroba.udea.edu.co/pluginfile.php/4/assignsubmission_file/submission_files/student.pdf"
        ))
        self.assertFalse(_is_safe_pluginfile(
            "https://udearroba.udea.edu.co/pluginfile.php/4/mod_assign/introattachment/0/task.pdf",
            "resource",
        ))
        self.assertTrue(_is_safe_pluginfile(
            "https://udearroba.udea.edu.co/pluginfile.php/4/mod_assign/introattachment/0/task.pdf",
            "assign",
        ))
        self.assertTrue(_is_safe_pluginfile(
            "https://udearroba.udea.edu.co/pluginfile.php/4/mod_page/content/0/diagram.png",
            "page",
        ))
        self.assertTrue(_is_safe_pluginfile(
            "https://udearroba.udea.edu.co/pluginfile.php/3389426/mod_folder/content/0/lecture.pdf",
            "folder",
        ))

    def test_page_extraction_returns_readable_text_without_scripts(self):
        soup = BeautifulSoup(
            '<main id="region-main"><div class="no-overflow"><h2>Unidad 1</h2>'
            '<p>Contenido de la clase</p><script>alert("x")</script></div></main>',
            "html.parser",
        )

        text = _page_text(soup)

        self.assertIn("Unidad 1", text)
        self.assertIn("Contenido de la clase", text)
        self.assertNotIn("alert", text)

    def test_rejects_course_url_that_redirects_to_enrollment(self):
        response = Mock()
        response.url = "https://ingenia.udea.edu.co/campus/enrol/index.php?id=215"
        response.raise_for_status.return_value = None
        session = Mock()
        session.get.return_value = response

        with TemporaryDirectory() as directory:
            with patch("claude_udea.materials.discover_course_url", return_value="https://ingenia.udea.edu.co/campus/course/view.php?id=215"):
                with self.assertRaisesRegex(PermissionError, "matrícula"):
                    scrape_course_materials(
                        session,
                        {"name": "Ingenia course", "course_url": "https://ingenia.udea.edu.co/campus/course/view.php?id=215"},
                        Path(directory),
                    )


if __name__ == "__main__":
    unittest.main()