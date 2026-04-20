# ADB 설치 가이드

이 프로젝트는 ADB(Android Debug Bridge)를 내장하여 사용합니다.

## 자동 설치 스크립트 (권장)

Windows에서 다음 명령어를 실행하면 ADB가 자동으로 다운로드됩니다:

```bash
python setup_adb.py
```

## 수동 설치

1. [Android SDK Platform Tools](https://developer.android.com/studio/releases/platform-tools) 다운로드
2. 압축 해제 후 다음 파일들을 `tools/adb/` 폴더에 복사:
   - `adb.exe`
   - `AdbWinApi.dll`
   - `AdbWinUsbApi.dll`

## 확인

```bash
python -c "from src.adb_controller import ADBController; adb = ADBController(); print('ADB 경로:', adb.adb_path)"
```

## 라이선스

Android SDK Platform Tools는 Apache License 2.0 하에 배포됩니다.
