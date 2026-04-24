import subprocess
import unittest
from unittest.mock import patch

from src.adb_controller import ADBController


class RecordingADBController(ADBController):
    def __init__(self):
        self.device_id = "127.0.0.1:5555"
        self.input_profile = "default"
        self.adb_path = "adb"
        self.commands = []
        self.returncodes = []

    def _run_adb(self, args, text=False):
        self.commands.append(args)
        returncode = self.returncodes.pop(0) if self.returncodes else 0
        stdout = "" if text else b""
        stderr = "" if text else b""
        return subprocess.CompletedProcess([self.adb_path, *args], returncode, stdout=stdout, stderr=stderr)


class ADBControllerSwipeTest(unittest.TestCase):
    @patch("src.adb_controller.time.sleep", return_value=None)
    def test_mumu_profile_prefers_motionevent_drag(self, _sleep):
        controller = RecordingADBController()
        controller.set_input_profile("mumu")

        result = controller.swipe(100, 600, 100, 200, duration=500, delay=0.1)

        self.assertTrue(result)
        self.assertGreaterEqual(len(controller.commands), 3)
        self.assertEqual(controller.commands[0][4:6], ["motionevent", "DOWN"])
        self.assertEqual(controller.commands[-1][4:6], ["motionevent", "UP"])

    @patch("src.adb_controller.time.sleep", return_value=None)
    def test_mumu_profile_falls_back_to_standard_swipe(self, _sleep):
        controller = RecordingADBController()
        controller.set_input_profile("mumu")
        controller.returncodes = [1, 0, 0, 0]

        result = controller.swipe(100, 600, 100, 200, duration=500, delay=0.1)

        self.assertTrue(result)
        self.assertIn(["-s", "127.0.0.1:5555", "shell", "input", "touchscreen", "swipe", "100", "600", "100", "200", "500"], controller.commands)

    @patch("src.adb_controller.time.sleep", return_value=None)
    def test_default_profile_uses_standard_swipe_only(self, _sleep):
        controller = RecordingADBController()

        result = controller.swipe(100, 600, 100, 200, duration=500, delay=0.1)

        self.assertTrue(result)
        self.assertEqual(controller.commands[0][4:6], ["touchscreen", "swipe"])


if __name__ == "__main__":
    unittest.main()
