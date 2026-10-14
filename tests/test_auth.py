import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from bs4 import BeautifulSoup

from claude_udea import auth


class SecureAuthStorageTests(unittest.TestCase):
    def make_keyring(self):
        values = {}
        backend = Mock()
        backend.get_password.side_effect = lambda service, account: values.get(account)
        backend.set_password.side_effect = lambda service, account, value: values.__setitem__(account, value)
        return backend, values

    def test_credentials_are_written_to_keyring_not_plaintext_file(self):
        backend, values = self.make_keyring()
        with tempfile.TemporaryDirectory() as temporary_directory:
            work_dir = Path(temporary_directory)
            with patch.object(auth, "_keyring_backend", return_value=backend):
                auth._save_credentials(work_dir, "student", "password")

            self.assertFalse((work_dir / auth.CREDENTIALS_FILE).exists())
        self.assertEqual(
            json.loads(values[auth.CREDENTIALS_ACCOUNT]),
            {"username": "student", "password": "password"},
        )

    def test_migrates_legacy_json_only_after_verified_keyring_write(self):
        backend, values = self.make_keyring()
        with tempfile.TemporaryDirectory() as temporary_directory:
            work_dir = Path(temporary_directory)
            session_path = work_dir / auth.SESSION_FILE
            credentials_path = work_dir / auth.CREDENTIALS_FILE
            session_path.write_text('[{"name":"sid","value":"secret"}]', encoding="utf-8")
            credentials_path.write_text(
                '{"username":"student","password":"password"}',
                encoding="utf-8",
            )

            with patch.object(auth, "_keyring_backend", return_value=backend):
                migrated = auth.migrate_saved_secrets(work_dir)

            self.assertEqual(migrated, [auth.SESSION_FILE, auth.CREDENTIALS_FILE])
            self.assertFalse(session_path.exists())
            self.assertFalse(credentials_path.exists())

    def test_loads_session_from_keyring_without_json_file(self):
        backend, values = self.make_keyring()
        values[auth.SESSION_ACCOUNT] = json.dumps([
            {"name": "sid", "value": "secret", "domain": "udearroba.udea.edu.co", "path": "/"}
        ])
        session = Mock()
        session.get.return_value = SimpleNamespace(
            url=auth.DASHBOARD_URL,
            status_code=200,
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            with (
                patch.object(auth, "_keyring_backend", return_value=backend),
                patch.object(auth.requests, "Session", return_value=session),
            ):
                loaded = auth.load_session(Path(temporary_directory))

        self.assertIs(loaded, session)
        session.cookies.set.assert_called_once_with(
            "sid",
            "secret",
            domain="udearroba.udea.edu.co",
            path="/",
        )


class MoodleRecordingPaginationTests(unittest.TestCase):
    @staticmethod
    def page(recording_id, pager=""):
        return f"""
        <table class="generaltable"><tbody>
          <tr><td>meeting</td><td>Architecture</td><td>2026-09-01</td><td>60</td>
          <td><input name="zoomplayredirect" value="https://zoom.example/rec/share/{recording_id}"></td></tr>
        </tbody></table>{pager}
        """

    def test_scrapes_all_same_activity_pager_pages_and_deduplicates_ids(self):
        initial_url = "https://udearroba.udea.edu.co/internos/mod/recordingszoom/recordinglist.php?id=123"
        page_two = initial_url + "&page=1"
        page_three = initial_url + "&page=2"
        responses = {
            initial_url: self.page("rec-1", f'<div class="pagination"><a href="{page_two}">Siguiente</a></div>'),
            page_two: self.page("rec-2", f'<nav class="pagination"><a href="{page_three}">Next</a></nav>'),
            page_three: self.page("rec-2", f'<div class="pagination"><a href="{page_two}">Previous</a></div>'),
        }
        session = Mock()
        session.get.side_effect = lambda url, **kwargs: SimpleNamespace(
            url=url, text=responses[url], raise_for_status=Mock()
        )

        slug, links = auth._scrape_one(
            session, "architecture", {"name": "Architecture", "moodle_url": initial_url}
        )

        self.assertEqual(slug, "architecture")
        self.assertEqual([link["id"] for link in links], ["rec-1", "rec-2"])
        self.assertEqual(session.get.call_count, 3)

    def test_does_not_follow_pager_links_to_a_different_activity(self):
        initial_url = "https://udearroba.udea.edu.co/internos/mod/recordingszoom/recordinglist.php?id=123"
        other_url = "https://udearroba.udea.edu.co/internos/mod/recordingszoom/recordinglist.php?id=999&page=1"
        response = SimpleNamespace(
            url=initial_url,
            text=self.page("rec-1", f'<div class="pagination"><a href="{other_url}">Next</a></div>'),
            raise_for_status=Mock(),
        )
        session = Mock()
        session.get.return_value = response

        _, links = auth._scrape_one(
            session, "architecture", {"name": "Architecture", "moodle_url": initial_url}
        )

        self.assertEqual(len(links), 1)
        self.assertEqual(session.get.call_count, 1)


class MoodleDateWindowTests(unittest.TestCase):
    def test_detects_date_range_fields(self):
        soup = BeautifulSoup(
            '<form method="get"><input name="from" type="date">'
            '<input name="to" type="date"><input name="sesskey" value="x"></form>',
            "html.parser",
        )
        self.assertEqual(auth._detect_date_range_fields(soup), ("from", "to"))

    def test_scrape_iterates_date_windows(self):
        initial_url = "https://udearroba.udea.edu.co/internos/mod/recordingszoom/recordinglist.php?id=123"

        def record_page(rec_id):
            return (
                '<form method="get"><input name="from" type="date">'
                '<input name="to" type="date"></form>'
                '<table class="generaltable"><tbody>'
                f'<tr><td>m</td><td>T</td><td>2026-08-05</td><td>60</td>'
                f'<td><input name="zoomplayredirect" value="https://zoom.example/rec/share/{rec_id}"></td></tr>'
                '</tbody></table>'
            )

        responses = {
            initial_url: record_page("rec-0"),
            auth._append_params(initial_url, {"from": "2026-08-01", "to": "2026-08-30"}): record_page("rec-1"),
            auth._append_params(initial_url, {"from": "2026-08-31", "to": "2026-09-29"}): record_page("rec-2"),
        }
        session = Mock()
        session.get.side_effect = lambda url, **kwargs: SimpleNamespace(
            url=url, text=responses[url], raise_for_status=Mock()
        )

        with patch.object(
            auth,
            "_date_windows",
            return_value=[("2026-08-01", "2026-08-30"), ("2026-08-31", "2026-09-29")],
        ):
            slug, links = auth._scrape_one(
                session, "architecture", {"name": "Architecture", "moodle_url": initial_url}
            )

        self.assertEqual(slug, "architecture")
        self.assertEqual([link["id"] for link in links], ["rec-1", "rec-2"])


if __name__ == "__main__":
    unittest.main()
