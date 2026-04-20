"""
ADB 통신을 위한 컨트롤러 모듈
"""
import subprocess
import time
import os
import sys
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
    
    def get_devices(self) -> list:
        """
        연결된 ADB 디바이스 목록 가져오기
        
        Returns:
            디바이스 정보 리스트 [{'id': 'device_id', 'status': 'device'}, ...]
        """
        try:
            result = self._run_adb(["devices"], text=True)
            
            devices = []
            lines = result.stdout.strip().split('\n')[1:]  # 첫 줄(헤더) 제외
            
            for line in lines:
                if '\t' in line:
                    parts = line.split('\t')
                    if len(parts) >= 2:
                        device_id = parts[0].strip()
                        status = parts[1].strip()
                        if device_id:  # 빈 라인 제외
                            devices.append({'id': device_id, 'status': status})
                    
            return devices
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
            self._run_adb(["-s", self.device_id, "shell", "input", "tap", str(x), str(y)])
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
            self._run_adb([
                "-s", self.device_id, "shell", "input", "swipe",
                str(x1), str(y1), str(x2), str(y2), str(duration)
            ])
            logger.debug(f"스와이프: ({x1}, {y1}) -> ({x2}, {y2})")
            time.sleep(delay)
            return True
        except Exception as e:
            logger.error(f"스와이프 실행 중 오류: {e}")
            return False
    
    def screenshot(self, save_path: str) -> bool:
        """
        화면 캡처
        
        Args:
            save_path: 저장할 파일 경로
            
        Returns:
            캡처 성공 여부
        """
        try:
            # 디바이스에서 스크린샷 촬영
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
                # 특정 디바이스만 연결 해제
                result = self._run_adb(["disconnect", self.device_id], text=True)
                logger.info(f"디바이스 연결 해제: {self.device_id}")
                logger.debug(result.stdout)
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
