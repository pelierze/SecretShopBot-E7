# 이벤트 기능 보관

2026-10-10 종료된 여름 이벤트 기능을 앱에서 분리한 원본입니다.
이벤트 탭은 현재 앱에 유지하며 “현재 지원하는 이벤트가 없습니다” 안내만 표시합니다.

- `src/event/`: 이벤트 공통 모델과 2026 여름 이벤트 자동화 코드·설정
- `images/2026_summer_event/`: 이벤트 인식 이미지
- `docs/2026_summer_event/`: 이벤트 계획·사용 문서
- `tests/event/`: 이벤트 전용 테스트
- `src/gui.py`, `tests/test_gui.py`, `tests/test_stove_suite.py`, `tests/test_scrollable_gui.py`: 이벤트 연동 제거 전 공통 파일 스냅샷
- `SecretShopBot-E7.spec`, `build_support/release_assets.py`: 제거 전 배포 구성
- `README.original.md`: 제거 전 앱 사용 안내

공통 파일은 당시 맥락 보존용입니다. 현재 파일을 덮어쓰면 다른 기능의 변경도 되돌아갈 수 있습니다.
보관된 코드는 현재 앱에서 가져오거나 배포하지 않으며, 활성 테스트 수집 대상도 아닙니다.
자동 탐사의 이벤트 선택 기능은 별도로 유지합니다.
