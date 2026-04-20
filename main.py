"""
에픽세븐 비밀상점 자동화 매크로
메인 실행 파일
"""
import sys
import logging
from pathlib import Path

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.gui import run_gui


def main():
    """메인 함수"""
    # 로그 디렉토리 생성
    log_dir = project_root / "logs"
    log_dir.mkdir(exist_ok=True)
    
    # GUI 실행
    run_gui()


if __name__ == "__main__":
    main()
