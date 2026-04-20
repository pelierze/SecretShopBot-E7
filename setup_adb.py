"""
ADB 자동 다운로드 및 설치 스크립트
"""
import os
import sys
import urllib.request
import zipfile
import shutil
from pathlib import Path

def download_adb():
    """ADB Platform Tools 다운로드 및 설치"""
    print("=" * 60)
    print("ADB (Android Debug Bridge) 자동 설치")
    print("=" * 60)
    
    # 프로젝트 루트 디렉토리
    project_root = Path(__file__).parent
    tools_dir = project_root / "tools" / "adb"
    tools_dir.mkdir(parents=True, exist_ok=True)
    
    # ADB가 이미 있는지 확인
    adb_exe = tools_dir / "adb.exe"
    if adb_exe.exists():
        print(f"\n✅ ADB가 이미 설치되어 있습니다: {adb_exe}")
        response = input("\n다시 다운로드하시겠습니까? (y/N): ")
        if response.lower() != 'y':
            print("\n설치를 취소합니다.")
            return
    
    # Windows용 Platform Tools URL
    url = "https://dl.google.com/android/repository/platform-tools-latest-windows.zip"
    zip_path = project_root / "platform-tools.zip"
    
    print(f"\n📥 다운로드 중: {url}")
    print("잠시만 기다려주세요... (약 10-20MB)")
    
    try:
        # 다운로드
        urllib.request.urlretrieve(url, zip_path)
        print("✅ 다운로드 완료!")
        
        # 압축 해제
        print("\n📦 압축 해제 중...")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(project_root)
        
        # 필요한 파일만 복사
        platform_tools_dir = project_root / "platform-tools"
        
        files_to_copy = [
            "adb.exe",
            "AdbWinApi.dll",
            "AdbWinUsbApi.dll"
        ]
        
        print("\n📁 파일 복사 중...")
        for filename in files_to_copy:
            src = platform_tools_dir / filename
            dst = tools_dir / filename
            if src.exists():
                shutil.copy2(src, dst)
                print(f"  ✅ {filename}")
            else:
                print(f"  ⚠️  {filename} 을(를) 찾을 수 없습니다.")
        
        # 정리
        print("\n🧹 임시 파일 정리 중...")
        zip_path.unlink()
        shutil.rmtree(platform_tools_dir)
        
        print("\n" + "=" * 60)
        print("✅ ADB 설치 완료!")
        print("=" * 60)
        print(f"\n설치 경로: {tools_dir}")
        print("\n이제 main.py를 실행하여 프로그램을 사용할 수 있습니다.")
        
    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        print("\n수동 설치를 권장합니다.")
        print("자세한 내용은 tools/INSTALL_ADB.md를 참고하세요.")
        sys.exit(1)

if __name__ == "__main__":
    try:
        download_adb()
    except KeyboardInterrupt:
        print("\n\n설치가 취소되었습니다.")
        sys.exit(0)
