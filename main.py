"""
에픽세븐 비밀상점 자동화 매크로
메인 실행 파일
"""
import os
import sys
import logging
from pathlib import Path
import warnings

# libpng 경고 메시지 숨기기 (가장 먼저 설정)
os.environ['OPENCV_LOG_LEVEL'] = 'ERROR'
os.environ['OPENCV_VIDEOIO_DEBUG'] = '0'

# stderr의 libpng 경고 필터링
class StderrFilter:
    def __init__(self, stream):
        self.stream = stream
        
    def write(self, data):
        if self.stream is None:
            return
        # libpng 경고 메시지 필터링
        if 'libpng warning' not in data and 'sBIT: invalid' not in data:
            self.stream.write(data)
            
    def flush(self):
        if self.stream is None:
            return
        self.stream.flush()

sys.stderr = StderrFilter(sys.stderr)

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def main():
    """메인 함수"""
    from src.runtime_diagnostics import diagnostic_logger
    startup_logger = diagnostic_logger('startup')
    # 항상 작업 디렉토리를 프로젝트 루트로 고정
    os.chdir(str(project_root))

    # libpng 경고를 stderr에서 제거
    import warnings
    warnings.filterwarnings("ignore")
    
    # 로그 디렉토리 생성
    log_dir = project_root / "logs"
    log_dir.mkdir(exist_ok=True)
    
    # Windows 환경에서 항상 관리자 권한(UAC) 확인 및 자동 승격 실행
    if sys.platform == "win32":
        import ctypes
        if not ctypes.windll.shell32.IsUserAnAdmin():
            startup_logger.info('Requesting administrator elevation')
            script_path = str(Path(sys.argv[0]).resolve())
            args = [script_path] + [a for a in sys.argv[1:] if a != "--admin"]
            params = " ".join(f'"{a}"' for a in args)

            # pythonw.exe를 사용하여 불필요한 cmd 콘솔 창 및 작업 표시줄 중복 아이콘 제거
            exe_dir = Path(sys.executable).parent
            pythonw = exe_dir / "pythonw.exe"
            target_exe = str(pythonw) if pythonw.exists() else sys.executable

            ret = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", target_exe, params, str(project_root), 1
            )
            startup_logger.info('Administrator elevation result: %s', int(ret))
            if int(ret) > 32:
                sys.exit(0)
            else:
                print("[경고] 관리자 권한 승인이 거부되었습니다. 일반 권한으로 계속 진행합니다.")

    # GUI 실행
    from src.gui import run_gui
    startup_logger.info('GUI module loaded; entering application')
    ready = None
    if len(sys.argv) == 3 and sys.argv[1] == '--update-ready':
        ready = Path(sys.argv[2]).resolve()
        if not ready.parent.name.startswith('.e7-update-') or ready.name != 'app-ready':
            raise ValueError('Invalid update acknowledgement path')
    run_gui(update_ready=ready)


if __name__ == "__main__":
    from src.runtime_diagnostics import diagnostic_logger, diagnostic_path
    startup_logger = diagnostic_logger('startup')
    startup_logger.info('Application starting: executable=%s; frozen=%s; arguments=%s',
                        sys.executable, getattr(sys, 'frozen', False), sys.argv[1:])
    try:
        main()
    except Exception:
        startup_logger.exception('Application startup or main loop failed')
        if sys.platform == 'win32' and getattr(sys, 'frozen', False):
            import ctypes
            ctypes.windll.user32.MessageBoxW(None,
                '앱 실행 중 오류가 발생했습니다.\n진단 로그: ' + diagnostic_path(startup_logger),
                '실행 오류', 0x10)
        raise
