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
    def test_mumu_profile_prefers_root_swipe(self, _sleep):
        controller = RecordingADBController()
        controller.set_input_profile("mumu")

        result = controller.swipe(100, 600, 100, 200, duration=500, delay=0.1)

        self.assertTrue(result)
        self.assertEqual(
            controller.commands[0],
            ["-s", "127.0.0.1:5555", "shell", "su", "0", "input", "swipe", "100", "600", "100", "200", "200"],
        )

    @patch("src.adb_controller.time.sleep", return_value=None)
    def test_mumu_profile_falls_back_to_motionevent_drag(self, _sleep):
        controller = RecordingADBController()
        controller.set_input_profile("mumu")
        controller.returncodes = [1, 1, 0, 0, 0, 0]

        result = controller.swipe(100, 600, 100, 200, duration=500, delay=0.1)

        self.assertTrue(result)
        self.assertEqual(controller.commands[2][4:6], ["motionevent", "DOWN"])
        self.assertEqual(controller.commands[-1][4:6], ["motionevent", "UP"])

    @patch("src.adb_controller.time.sleep", return_value=None)
    def test_mumu_profile_falls_back_to_standard_swipe(self, _sleep):
        controller = RecordingADBController()
        controller.set_input_profile("mumu")
        controller.returncodes = [1, 1, 1, 0]

        result = controller.swipe(100, 600, 100, 200, duration=500, delay=0.1)

        self.assertTrue(result)
        self.assertIn(
            ["-s", "127.0.0.1:5555", "shell", "input", "touchscreen", "swipe", "100", "600", "100", "200", "200"],
            controller.commands,
        )

    @patch("src.adb_controller.time.sleep", return_value=None)
    def test_default_profile_uses_standard_swipe_only(self, _sleep):
        controller = RecordingADBController()

        result = controller.swipe(100, 600, 100, 200, duration=500, delay=0.1)

        self.assertTrue(result)
        self.assertEqual(
            controller.commands[0],
            ["-s", "127.0.0.1:5555", "shell", "input", "touchscreen", "swipe", "100", "600", "100", "200", "200"],
        )

    def test_get_screen_size_prefers_logical_viewport(self):
        controller = RecordingADBController()

        def fake_run(args, text=False):
            if args[-2:] == ["dumpsys", "input"]:
                return subprocess.CompletedProcess(
                    [controller.adb_path, *args],
                    0,
                    stdout=(
                        "Viewport INTERNAL: displayId=0, orientation=1, "
                        "logicalFrame=[0, 0, 1280, 720], physicalFrame=[0, 0, 1280, 720]"
                    ),
                    stderr="",
                )
            if args[-2:] == ["wm", "size"]:
                return subprocess.CompletedProcess(
                    [controller.adb_path, *args],
                    0,
                    stdout="Physical size: 720x1280",
                    stderr="",
                )
            raise AssertionError(args)

        controller._run_adb = fake_run
        self.assertEqual(controller.get_screen_size(), (1280, 720))


if __name__ == "__main__":
    unittest.main()
