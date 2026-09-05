import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np

from src.gui import SessionView
from src.image_matcher import matching_failure_guidance


class ImageMatchingDiagnosticsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.template_path = self.root / "성약_covenant_bookmark.PNG"
        template = np.random.default_rng(7).integers(0, 256, (8, 8, 3), dtype=np.uint8)
        cv2.imencode(".png", template)[1].tofile(str(self.template_path))
        self.view = object.__new__(SessionView)
        self.view.name = "세션 1"
        self.view.runtime_dir = self.root / "logs"
        self.view.adb_controller = Mock()
        self.view.covenant_bookmark_threshold = Mock()
        self.view.covenant_bookmark_threshold.get.return_value = "95"

    def capture(self, path):
        screen = np.zeros((32, 32, 3), dtype=np.uint8)
        cv2.imencode(".png", screen)[1].tofile(path)
        return True

    def test_reported_scores_do_not_recommend_lower_thresholds(self):
        for score in (0.3548, 0.4511):
            with self.subTest(score=score):
                message = matching_failure_guidance(score)
                self.assertIn("임계값 하향을 권장하지 않습니다", message)
                self.assertIn("대상 아이템", message)
                self.assertNotIn("권장 임계값:", message)

    def test_failed_capture_does_not_read_previous_screenshot(self):
        self.view.runtime_dir.mkdir()
        stale = self.view.runtime_dir / "test_screenshot.png"
        stale.write_bytes(b"old screenshot")
        self.view.adb_controller.screenshot.return_value = False
        with patch("src.gui.read_image") as read, patch("src.gui.logger") as logger:
            self.view._run_image_test(str(self.template_path))
        read.assert_not_called()
        self.assertEqual(stale.read_bytes(), b"old screenshot")
        self.assertIn("캡처에 실패", logger.error.call_args.args[0])

    def test_repeated_tests_preserve_evidence_and_warn_on_absent_item(self):
        self.view.adb_controller.screenshot.side_effect = self.capture
        with patch("src.gui.logger") as logger:
            self.view._run_image_test(str(self.template_path))
            self.view._run_image_test(str(self.template_path))
        folders = list(self.view.runtime_dir.iterdir())
        self.assertEqual(len(folders), 2)
        for folder in folders:
            self.assertTrue((folder / "screenshot.png").is_file())
            self.assertEqual((folder / "template.PNG").read_bytes(), self.template_path.read_bytes())
        messages = [str(call.args) for call in logger.warning.call_args_list]
        self.assertTrue(any("임계값 하향을 권장하지 않습니다" in message for message in messages))
        self.assertFalse(any("권장 임계값:" in message for message in messages))
        logger.error.assert_not_called()

    def test_oversized_template_is_rejected_before_opencv_matching(self):
        def capture_small(path):
            cv2.imencode(".png", np.zeros((4, 4, 3), dtype=np.uint8))[1].tofile(path)
            return True

        self.view.adb_controller.screenshot.side_effect = capture_small
        with patch("cv2.matchTemplate") as match, patch("src.gui.logger") as logger:
            self.view._run_image_test(str(self.template_path))
        match.assert_not_called()
        self.assertIn("템플릿이 스크린샷보다 큽니다", logger.error.call_args.args[0])
