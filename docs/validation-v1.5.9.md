# v1.5.9 개발 검증 기록

2026-10-05, Windows / Python 3.12.10에서 확인했다.

- 전리품 버튼 인식과 보급·전투·상점 결과 팝업 흐름 관련 검사 99개 통과. 실행 상세 및 실제 사용자 제보의 확인 범위는 `docs/reviews/2026-10-05-reward-screen-recognition.md`에 기록했다.
- 배포 준비 시 `python -m unittest tests.test_release_assets tests.test_release_checker`: 8개 통과(3.021초).
- 앱 버전·기본 빌드 버전·Windows 파일 및 제품 버전을 `1.5.9`로 갱신했다.
- `build_release.ps1 -Version 1.5.9`: 앱과 업데이터 빌드 및 런타임 자산 검증 완료. 로그는 로컬 `logs/build-v1.5.9.log`에 있다.
- ZIP CRC, SHA256 일치, 최상위 버전 폴더, 실행 파일 두 개 및 배포 EXE 내부 앱 버전 확인.
- 배포 EXE 내부의 상점·보급·구매 확인·공통 팝업·승리 처리 코드가 현재 소스와 일치하는지 비교했다.
- ZIP의 이벤트 설정이 현재 소스와 일치하고, 검사 전용 사용자 제보 이미지가 배포에 포함되지 않는지 확인했다.
- 사용자용 릴리즈 노트에는 내부 검사 결과 및 체크섬 안내를 포함하지 않았다.
- `git diff --check`: 통과.

전체 discovery, 실제 게임 연속 동작, 새 배포 EXE의 GUI 실행과 자동 업데이트 설치는 수행하지 않았다.
