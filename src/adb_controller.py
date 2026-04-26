"""
ADB 통신을 위한 컨트롤러 모듈
"""
import subprocess
import time
import os
import sys
import re
import socket
from typing import Tuple, Optional
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


def get_resource_root() -> Path:
    """Return the folder that contains bundled resources."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


class ADBController:
    """ADB를 통해 앱플레이어와 통신하는 클래스"""
    
    def __init__(self, device_id: Optional[str] = None):
        """
        Args:
            device_id: ADB 디바이스 ID (None일 경우 자동 감지)
        """
        self.device_id = device_id
        self.input_profile = "default"
        
        # 프로젝트 내부의 ADB 경로 확인
        project_root = get_resource_root()
        adb_path = project_root / "tools" / "adb" / "adb.exe"
        
        if adb_path.exists():
            self.adb_path = str(adb_path)
            logger.info(f"프로젝트 내부 ADB 사용: {self.adb_path}")
        else:
            # ADB가 없으면 자동 다운로드
            logger.warning("ADB를 찾을 수 없습니다. 자동으로 다운로드합니다...")
            if self._download_adb(project_root):
                self.adb_path = str(adb_path)
                logger.info(f"ADB 다운로드 완료: {self.adb_path}")
            else:
                # 실패 시 시스템 PATH의 ADB 사용 시도
                self.adb_path = "adb"
                logger.warning("ADB 다운로드 실패. 시스템 PATH의 ADB를 사용합니다.")

    def set_input_profile(self, profile: Optional[str]) -> None:
        """입력 호환성 프로필 설정."""
        normalized = (profile or "default").strip().lower()
        if normalized not in {"default", "mumu"}:
            logger.warning("알 수 없는 입력 프로필 '%s' - 기본 프로필을 사용합니다.", profile)
            normalized = "default"
        self.input_profile = normalized
        logger.info("ADB 입력 프로필 설정: %s", self.input_profile)
    
    def _run_adb(self, args: list[str], text: bool = False) -> subprocess.CompletedProcess:
        """Run adb without flashing a console window on Windows."""
        kwargs = {
            "capture_output": True,
            "text": text,
        }

        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            kwargs["startupinfo"] = startupinfo
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        return subprocess.run([self.adb_path, *args], **kwargs)

    def _format_completed_output(self, result: subprocess.CompletedProcess) -> str:
        stdout = result.stdout if result.stdout is not None else ""
        stderr = result.stderr if result.stderr is not None else ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        return f"{stdout}\n{stderr}".strip()

    @staticmethod
    def _is_network_device_id(device_id: Optional[str]) -> bool:
        if not device_id or ":" not in device_id:
            return False
        host, _, port = device_id.rpartition(":")
        return bool(host and port.isdigit())

    def _can_connect_local_port(self, port: int) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return True
        except OSError:
            return False

    def _ensure_local_device_connections(self) -> None:
        known_ports = (5555, 5557, 62001, 7555, 16384, 16416, 21503, 21513)
        for port in known_ports:
            if not self._can_connect_local_port(port):
                continue
            self._run_adb(["connect", f"127.0.0.1:{port}"], text=True)

    def _get_device_identity(self, device_id: str) -> str:
        probes = [
            ["-s", device_id, "shell", "settings", "get", "secure", "android_id"],
            ["-s", device_id, "shell", "getprop", "ro.serialno"],
            ["-s", device_id, "shell", "getprop", "ro.product.model"],
        ]
        values = []
        for probe in probes:
            try:
                result = self._run_adb(probe, text=True)
            except Exception:
                continue
            output = self._format_completed_output(result).strip()
            if result.returncode == 0 and output and output.lower() != "null":
                values.append(output)
        return "|".join(values) if values else device_id

    @staticmethod
    def _device_preference_key(device: dict) -> tuple[int, str]:
        device_id = device.get("id", "")
        if device_id.startswith("emulator-"):
            return (0, device_id)
        if device_id.startswith("127.0.0.1:16384"):
            return (1, device_id)
        if ADBController._is_network_device_id(device_id):
            return (2, device_id)
        return (3, device_id)

    @staticmethod
    def _dedupe_group_key(device: dict, identity: str) -> str:
        device_id = device.get("id", "")
        if device_id.startswith("emulator-"):
            return f"emulator:{device_id}"
        if ADBController._is_network_device_id(device_id):
            return f"network:{identity}"
        return f"device:{device_id}"

    def _download_adb(self, project_root: Path) -> bool:
        """
        ADB 자동 다운로드
        
        Args:
            project_root: 프로젝트 루트 경로
            
        Returns:
            다운로드 성공 여부
        """
        import urllib.request
        import zipfile
        import shutil
        
        try:
            adb_dir = project_root / "tools" / "adb"
            adb_dir.mkdir(parents=True, exist_ok=True)
            
            # Google Platform Tools 다운로드 URL
            url = "https://dl.google.com/android/repository/platform-tools-latest-windows.zip"
            zip_path = project_root / "platform-tools.zip"
            
            logger.info(f"다운로드 중: {url}")
            urllib.request.urlretrieve(url, zip_path)
            logger.info("다운로드 완료!")
            
            # 압축 해제
            logger.info("압축 해제 중...")
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(project_root)
            
            # 필요한 파일만 복사
            logger.info("파일 복사 중...")
            platform_tools_dir = project_root / "platform-tools"
            
            for file in platform_tools_dir.glob("*"):
                if file.is_file():
                    shutil.copy2(file, adb_dir)
            
            # 임시 파일 삭제
            zip_path.unlink()
            shutil.rmtree(platform_tools_dir)
            
            logger.info("✅ ADB 설치 완료!")
            return True
            
        except Exception as e:
            logger.error(f"ADB 다운로드 중 오류: {e}")
            return False
        
    def connect(self, ip: str = "127.0.0.1", port: int = 5555) -> bool:
        """
        ADB 디바이스에 연결
        
        Args:
            ip: 연결할 IP 주소
            port: 연결할 포트 번호
            
        Returns:
            연결 성공 여부
        """
        try:
            result = self._run_adb(["connect", f"{ip}:{port}"], text=True)
            
            output = f"{result.stdout}\n{result.stderr}".lower()
            if "connected" in output or "already connected" in output:
                self.device_id = f"{ip}:{port}"
                logger.info(f"ADB 연결 성공: {self.device_id}")
                return True
            else:
                logger.error(f"ADB 연결 실패: {result.stdout}")
                return False
        except Exception as e:
            logger.error(f"ADB 연결 중 오류: {e}")
            return False

    def connect_device(self, device_id: str) -> bool:
        """Connect to an already-visible ADB device by serial/device id."""
        normalized = (device_id or "").strip()
        if not normalized:
            logger.error("ADB device id is empty.")
            return False

        if self._is_network_device_id(normalized):
            host, _, port = normalized.rpartition(":")
            return self.connect(host, int(port))

        try:
            result = self._run_adb(["-s", normalized, "get-state"], text=True)
            output = self._format_completed_output(result).lower()
            if result.returncode == 0 and "device" in output:
                self.device_id = normalized
                logger.info("ADB direct device selection successful: %s", self.device_id)
                return True
            logger.error("ADB direct device selection failed: %s", output)
            return False
        except Exception as e:
            logger.error("ADB direct device selection error: %s", e)
            return False

    def test_connection(self) -> tuple[bool, str]:
        """Verify that the connected device accepts ADB shell commands."""
        if not self.device_id:
            return False, "ADB 장치가 선택되지 않았습니다."

        try:
            result = self._run_adb(["-s", self.device_id, "shell", "echo", "SECRET_SHOP_ADB_OK"], text=True)
            output = self._format_completed_output(result)
            if result.returncode == 0 and "SECRET_SHOP_ADB_OK" in output:
                return True, "ADB 테스트 통신 성공"
            return False, output or f"ADB shell 명령 실패 (returncode={result.returncode})"
        except Exception as e:
            return False, str(e)
    
    def get_devices(self) -> list:
        """
        연결된 ADB 디바이스 목록 가져오기
        
        Returns:
            디바이스 정보 리스트 [{'id': 'device_id', 'status': 'device'}, ...]
        """
        try:
            self._ensure_local_device_connections()
            result = self._run_adb(["devices", "-l"], text=True)
            
            devices = []
            lines = result.stdout.strip().split("\n")[1:]

            for line in lines:
                parts = line.split()
                if len(parts) < 2:
                    continue
                device_id = parts[0].strip()
                status = parts[1].strip()
                device = {"id": device_id, "status": status}
                for token in parts[2:]:
                    if ":" not in token:
                        continue
                    key, value = token.split(":", 1)
                    if key and value:
                        device[key] = value
                if device_id:
                    devices.append(device)

            identities = {
                device["id"]: self._get_device_identity(device["id"])
                for device in devices
            }
            emulator_identities = {
                identity
                for device_id, identity in identities.items()
                if device_id.startswith("emulator-")
            }

            unique_devices = {}
            for device in devices:
                device_id = device["id"]
                identity = identities[device_id]
                if self._is_network_device_id(device_id) and identity in emulator_identities:
                    continue

                group_key = self._dedupe_group_key(device, identity)
                current = unique_devices.get(group_key)
                if current is None or self._device_preference_key(device) < self._device_preference_key(current):
                    unique_devices[group_key] = device

            return sorted(unique_devices.values(), key=self._device_preference_key)
        except Exception as e:
            logger.error(f"디바이스 목록 조회 중 오류: {e}")
            return []
    
    def tap(self, x: int, y: int, delay: float = 0.5) -> bool:
        """
        화면의 특정 좌표 터치
        
        Args:
            x: X 좌표
            y: Y 좌표
            delay: 터치 후 대기 시간 (초)
            
        Returns:
            실행 성공 여부
        """
        try:
            result = self._run_adb(["-s", self.device_id, "shell", "input", "tap", str(x), str(y)])
            if result.returncode != 0:
                logger.error(f"터치 실행 실패: {self._format_completed_output(result)}")
                return False
            logger.debug(f"터치: ({x}, {y})")
            time.sleep(delay)
            return True
        except Exception as e:
            logger.error(f"터치 실행 중 오류: {e}")
            return False
    
    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: int = 300, delay: float = 0.5) -> bool:
        """
        화면 스와이프 (드래그)
        
        Args:
            x1: 시작 X 좌표
            y1: 시작 Y 좌표
            x2: 종료 X 좌표
            y2: 종료 Y 좌표
            duration: 스와이프 지속 시간 (밀리초)
            delay: 스와이프 후 대기 시간 (초)
            
        Returns:
            실행 성공 여부
        """
        try:
            effective_duration = self._normalize_swipe_duration(duration)
            if self.input_profile == "mumu":
                success, last_output = self._swipe_mumu_compat(x1, y1, x2, y2, effective_duration)
            else:
                success, last_output = self._swipe_standard(x1, y1, x2, y2, effective_duration)

            if success:
                logger.debug(
                    "스와이프(%s): (%s, %s) -> (%s, %s), duration=%s",
                    self.input_profile,
                    x1,
                    y1,
                    x2,
                    y2,
                    effective_duration,
                )
                time.sleep(delay)
                return True

            logger.error(f"스와이프 실행 실패: {last_output}")
            return False
        except Exception as e:
            logger.error(f"스와이프 실행 중 오류: {e}")
            return False

    def _swipe_standard(self, x1: int, y1: int, x2: int, y2: int, duration: int) -> tuple[bool, str]:
        return self._run_swipe_command_list(self._build_swipe_commands(x1, y1, x2, y2, duration))

    def _build_swipe_commands(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration: int,
        allow_root: bool = False,
    ) -> list[list[str]]:
        commands = [
            [
                "-s", self.device_id, "shell", "input", "touchscreen", "swipe",
                str(x1), str(y1), str(x2), str(y2), str(duration)
            ],
            [
                "-s", self.device_id, "shell", "input", "swipe",
                str(x1), str(y1), str(x2), str(y2), str(duration)
            ],
            [
                "-s", self.device_id, "shell", "input", "swipe",
                str(x1), str(y1), str(x2), str(y2)
            ],
        ]
        if allow_root:
            commands.extend(
                [
                    [
                        "-s", self.device_id, "shell", "su", "0", "input", "swipe",
                        str(x1), str(y1), str(x2), str(y2), str(duration)
                    ],
                    [
                        "-s", self.device_id, "shell", "su", "0", "input", "swipe",
                        str(x1), str(y1), str(x2), str(y2)
                    ],
                ]
            )
        return commands

    def _build_root_swipe_commands(self, x1: int, y1: int, x2: int, y2: int, duration: int) -> list[list[str]]:
        return [
            [
                "-s", self.device_id, "shell", "su", "0", "input", "swipe",
                str(x1), str(y1), str(x2), str(y2), str(duration)
            ],
            [
                "-s", self.device_id, "shell", "su", "0", "input", "swipe",
                str(x1), str(y1), str(x2), str(y2)
            ],
        ]

    def _normalize_swipe_duration(self, duration: int) -> int:
        return max(150, min(duration, 200))

    def _swipe_mumu_compat(self, x1: int, y1: int, x2: int, y2: int, duration: int) -> tuple[bool, str]:
        success, output = self._run_swipe_command_list(
            self._build_root_swipe_commands(x1, y1, x2, y2, duration)
        )
        if success:
            return True, output

        logger.warning("MuMu 루트 스와이프가 실패해 호환 드래그 명령으로 재시도합니다: %s", output)

        success, output = self._swipe_with_motionevent(x1, y1, x2, y2, duration)
        if success:
            return True, output

        logger.warning("MuMu 호환 드래그가 실패해 기본 스와이프 명령으로 재시도합니다: %s", output)
        return self._run_swipe_command_list(self._build_swipe_commands(x1, y1, x2, y2, duration))

    def _run_swipe_command_list(self, commands: list[list[str]]) -> tuple[bool, str]:
        last_output = ""
        for command in commands:
            result = self._run_adb(command)
            if result.returncode == 0:
                return True, ""
            last_output = self._format_completed_output(result)
        return False, last_output

    def _swipe_with_motionevent(self, x1: int, y1: int, x2: int, y2: int, duration: int) -> tuple[bool, str]:
        steps = max(4, min(12, duration // 100 if duration > 0 else 6))
        step_delay = max(0.01, duration / max(steps, 1) / 1000.0)

        events = [
            ["-s", self.device_id, "shell", "input", "motionevent", "DOWN", str(x1), str(y1)],
        ]
        for step in range(1, steps):
            progress = step / steps
            move_x = int(round(x1 + (x2 - x1) * progress))
            move_y = int(round(y1 + (y2 - y1) * progress))
            events.append(
                ["-s", self.device_id, "shell", "input", "motionevent", "MOVE", str(move_x), str(move_y)]
            )
        events.append(["-s", self.device_id, "shell", "input", "motionevent", "UP", str(x2), str(y2)])

        last_output = ""
        for index, event in enumerate(events):
            result = self._run_adb(event)
            if result.returncode != 0:
                last_output = self._format_completed_output(result)
                return False, last_output
            if index < len(events) - 1:
                time.sleep(step_delay)

        return True, ""
    
    def screenshot(self, save_path: str) -> bool:
        """
        화면 캡처
        
        Args:
            save_path: 저장할 파일 경로
            
        Returns:
            캡처 성공 여부
        """
        try:
            save_file = Path(save_path)
            save_file.parent.mkdir(parents=True, exist_ok=True)

            # exec-out으로 PNG bytes를 직접 받아 저장합니다. Windows 한글 경로에서 adb pull보다 안정적입니다.
            result = self._run_adb(["-s", self.device_id, "exec-out", "screencap", "-p"])
            if result.returncode == 0 and isinstance(result.stdout, bytes) and result.stdout.startswith(b"\x89PNG"):
                save_file.write_bytes(result.stdout)
                logger.debug(f"스크린샷 저장: {save_path}")
                return True

            logger.debug(f"exec-out 스크린샷 실패, pull 방식 재시도: {self._format_completed_output(result)}")

            # 디바이스에서 스크린샷 촬영 후 pull fallback
            screenshot_path = "/sdcard/screenshot.png"
            self._run_adb(["-s", self.device_id, "shell", "screencap", "-p", screenshot_path])
            
            # PC로 파일 전송
            result = self._run_adb(["-s", self.device_id, "pull", screenshot_path, save_path], text=True)
            
            if "pulled" in result.stdout.lower() or result.returncode == 0:
                logger.debug(f"스크린샷 저장: {save_path}")
                return True
            else:
                logger.error(f"스크린샷 저장 실패: {result.stdout}")
                return False
        except Exception as e:
            logger.error(f"스크린샷 촬영 중 오류: {e}")
            return False
    
    def get_screen_size(self) -> Tuple[int, int]:
        """
        화면 크기 가져오기
        
        Returns:
            (width, height) 튜플
        """
        try:
            result = self._run_adb(["-s", self.device_id, "shell", "dumpsys", "input"], text=True)
            output = self._format_completed_output(result)
            match = re.search(
                r"Viewport INTERNAL:.*?logicalFrame=\[\s*\d+,\s*\d+,\s*(\d+),\s*(\d+)\]",
                output,
                re.DOTALL,
            )
            if result.returncode == 0 and match:
                width, height = map(int, match.groups())
                logger.info("화면 입력 크기: %sx%s", width, height)
                return width, height

            result = self._run_adb(["-s", self.device_id, "shell", "wm", "size"], text=True)
            
            # "Physical size: 1920x1080" 형식의 출력 파싱
            size_str = result.stdout.strip().split(': ')[-1]
            width, height = map(int, size_str.split('x'))
            
            logger.info(f"화면 크기: {width}x{height}")
            return width, height
        except Exception as e:
            logger.error(f"화면 크기 조회 중 오류: {e}")
            return 1920, 1080  # 기본값
    
    def disconnect(self) -> bool:
        """
        ADB 연결 해제
        
        Returns:
            해제 성공 여부
        """
        try:
            if self.device_id:
                if self._is_network_device_id(self.device_id):
                    result = self._run_adb(["disconnect", self.device_id], text=True)
                    logger.info(f"디바이스 연결 해제: {self.device_id}")
                    logger.debug(result.stdout)
                else:
                    logger.info("ADB 장치 선택 해제: %s", self.device_id)
                self.device_id = None
            return True
        except Exception as e:
            logger.error(f"연결 해제 중 오류: {e}")
            return False
    
    def kill_server(self) -> bool:
        """
        ADB 서버 종료
        
        Returns:
            종료 성공 여부
        """
        try:
            result = self._run_adb(["kill-server"], text=True)
            logger.info("ADB 서버 종료됨")
            if result.stdout:
                logger.debug(result.stdout)
            return True
        except Exception as e:
            logger.error(f"ADB 서버 종료 중 오류: {e}")
            return False
