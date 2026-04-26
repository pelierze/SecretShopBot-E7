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
    def test_get_devices_auto_connects_local_ports_and_deduplicates_aliases(self):
        controller = RecordingADBController()

        def fake_can_connect(port):
            return port in {5555, 16384}

        def fake_identity(device_id):
            if device_id in {"127.0.0.1:5555", "127.0.0.1:16384", "emulator-5554"}:
                return "device-a"
            if device_id == "emulator-5564":
                return "device-b"
            return device_id

        def fake_run(args, text=False):
            controller.commands.append(args)
            if args[:1] == ["connect"]:
                return subprocess.CompletedProcess([controller.adb_path, *args], 0, stdout="connected", stderr="")
            if args == ["devices", "-l"]:
                return subprocess.CompletedProcess(
                    [controller.adb_path, *args],
                    0,
                    stdout=(
                        "List of devices attached\n"
                        "127.0.0.1:16384        device product:b5q model:SM_F731B device:b5q transport_id:5\n"
                        "127.0.0.1:5555         device product:b5q model:SM_F731B device:b5q transport_id:3\n"
                        "emulator-5554          device product:b5q model:SM_F731B device:b5q transport_id:1\n"
                        "emulator-5564          device product:b0qxxx model:SM_S908E device:b0q transport_id:2\n\n"
                    ),
                    stderr="",
                )
            raise AssertionError(args)

        controller._run_adb = fake_run
        controller._can_connect_local_port = fake_can_connect
        controller._get_device_identity = fake_identity

        devices = controller.get_devices()

        self.assertEqual(
            devices,
            [
                {
                    "id": "emulator-5554",
                    "status": "device",
                    "product": "b5q",
                    "model": "SM_F731B",
                    "device": "b5q",
                    "transport_id": "1",
                },
                {
                    "id": "emulator-5564",
                    "status": "device",
                    "product": "b0qxxx",
                    "model": "SM_S908E",
                    "device": "b0q",
                    "transport_id": "2",
                },
            ],
        )
        self.assertIn(["connect", "127.0.0.1:5555"], controller.commands)
        self.assertIn(["connect", "127.0.0.1:16384"], controller.commands)

    def test_get_devices_keeps_distinct_emulator_ids_even_if_identity_matches(self):
        controller = RecordingADBController()

        def fake_run(args, text=False):
            if args[:1] == ["connect"]:
                return subprocess.CompletedProcess([controller.adb_path, *args], 0, stdout="connected", stderr="")
            if args == ["devices", "-l"]:
                return subprocess.CompletedProcess(
                    [controller.adb_path, *args],
                    0,
                    stdout=(
                        "List of devices attached\n"
                        "127.0.0.1:5555         device product:b5q model:SM_F731B device:b5q transport_id:3\n"
                        "emulator-5554          device product:b5q model:SM_F731B device:b5q transport_id:1\n"
                        "emulator-5564          device product:b5q model:SM_F731B device:b5q transport_id:2\n\n"
                    ),
                    stderr="",
                )
            raise AssertionError(args)

        controller._run_adb = fake_run
        controller._can_connect_local_port = lambda port: port == 5555
        controller._get_device_identity = lambda device_id: "same-device-image"

        devices = controller.get_devices()

        self.assertEqual(
            [device["id"] for device in devices],
            ["emulator-5554", "emulator-5564"],
        )

    def test_connect_device_uses_direct_serial_for_emulator_ids(self):
        controller = RecordingADBController()

        def fake_run(args, text=False):
            self.assertEqual(args, ["-s", "emulator-5564", "get-state"])
            return subprocess.CompletedProcess(
                [controller.adb_path, *args],
                0,
                stdout="device",
                stderr="",
            )

        controller._run_adb = fake_run

        self.assertTrue(controller.connect_device("emulator-5564"))
        self.assertEqual(controller.device_id, "emulator-5564")

    def test_connect_device_routes_network_ids_through_connect(self):
        controller = RecordingADBController()

        with patch.object(controller, "connect", return_value=True) as connect_mock:
            self.assertTrue(controller.connect_device("127.0.0.1:5557"))

        connect_mock.assert_called_once_with("127.0.0.1", 5557)

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
