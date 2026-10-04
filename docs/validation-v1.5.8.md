# v1.5.8 개발 검증 기록

2026-10-04, Windows / Python 3.12.10에서 확인했다.

## 변경 범위

- 이벤트·휴식 랭크업 결과창, 전리품·레벨업 팝업의 닫기 확인과 제한된 재입력.
- 작업 폴더에 준비되어 있던 녹슨 철창 이벤트 규칙·이미지·검사 포함.
- 앱 버전, Windows 실행 파일 버전, 기본 빌드 버전을 `1.5.8`로 갱신.
- 사용자용 릴리즈 노트에는 변경 사항과 설치·업데이트 방법만 기록.

## 패키지 확인

- `build_release.ps1 -Version 1.5.8`: 앱과 업데이터 빌드, 런타임 자산 검증 완료.
- ZIP CRC, 최상위 `SecretShopBot-E7-v1.5.8` 폴더, SHA256 일치 확인.
- 배포 EXE의 내부 앱 버전과 Windows 파일·제품 버전 모두 `1.5.8` 확인.
- 배포 EXE에 새 팝업 닫기 처리 포함 확인.
- ZIP의 이벤트 설정과 녹슨 철창 이미지가 소스와 일치하는지 확인.
- 로컬 빌드 로그: `logs/build-v1.5.8.log`.

## 테스트와 제한

팝업·랭크업·이벤트 흐름·복구·노드 진행 관련 검사 95개 통과. 세부 실행 기록은
`docs/reviews/2026-10-04-popup-close-recovery.md`에 기록했다.

`python -m unittest tests.test_chaos_registered_events tests.test_release_assets tests.test_release_checker`:
13개 통과(158.416초). 변경 관련 검사 합계는 중복 제외 108개다.
`git diff --check`도 통과했다. 기존 PNG의 `sBIT: invalid` 경고는 검사 실패를 일으키지 않았다.

이번 버전에서는 변경 관련 검사와 배포 자산·업데이트 검사로 검증 범위를 한정했다.
전체 discovery는 재실행하지 않았다. 이전 버전의 여름 이벤트 검사 제한은
`docs/validation-v1.5.7.md`에 기록되어 있다. 실제 게임의 입력 지연 재현과
새 배포 EXE의 GUI 실행·자동 업데이트 설치는 확인하지 않았다.
