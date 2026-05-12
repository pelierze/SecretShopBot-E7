import unittest
from unittest.mock import patch

from src.release_checker import ReleaseInfo, get_available_update, parse_version


class ReleaseCheckerTest(unittest.TestCase):
    def test_parse_version_supports_v_prefix(self):
        self.assertEqual(parse_version("v1.2.3"), (1, 2, 3))
        self.assertEqual(parse_version("1.2.3-beta"), (1, 2, 3))

    @patch("src.release_checker.fetch_latest_release")
    def test_get_available_update_returns_release_when_newer(self, mock_fetch):
        mock_fetch.return_value = ReleaseInfo(
            version="v1.2.0",
            url="https://example.com/release",
            name="v1.2.0",
        )

        release = get_available_update(current_version="1.1.3")

        self.assertIsNotNone(release)
        self.assertEqual(release.version, "v1.2.0")

    @patch("src.release_checker.fetch_latest_release")
    def test_get_available_update_returns_none_when_same_or_older(self, mock_fetch):
        mock_fetch.return_value = ReleaseInfo(
            version="1.1.3",
            url="https://example.com/release",
            name="1.1.3",
        )

        release = get_available_update(current_version="1.1.3")

        self.assertIsNone(release)


if __name__ == "__main__":
    unittest.main()
