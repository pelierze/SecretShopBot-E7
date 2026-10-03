# v1.5.7 개발 검증 기록

2026-10-03, Windows / Python 3.12.10에서 확인했다.

## 변경 및 패키지 확인

- 업데이트 권한 및 영구 로그, 배포 자산, GUI 관련 검사 60개 통과.
- Windows 통합 검사에서 설치 폴더의 Users 읽기/실행 권한이 업데이트된
  EXE 두 개와 내부 파일에 적용되는 것을 확인했다.
- 권한 설정 실패 시 이전 파일 복구, 업데이트 임시 폴더 삭제 후 로그 보존 확인.
- `build_release.ps1 -Version 1.5.7` 빌드 및 런타임 파일 검증 완료.
- ZIP CRC, 최상위 버전 폴더 및 SHA256 일치 확인.
- 배포 EXE 내부의 버전 `1.5.7`, GUI 모듈, 앱과 업데이트 프로그램 양쪽의
  진단 모듈 포함 확인.
- 실제 배포 EXE로 관리자 권한 업데이트 후 일반 탐색기 실행은 확인하지 않았다.

## 전체 검사

`python -m unittest discover -s tests`: 464개 실행, 447개 통과,
2개 제외, 7개 실패, 8개 오류. 실행 시간 약 504초.

실패와 오류는 모두 이번에 수정하지 않은
`tests/event/test_2026_summer_event.py`에서 발생했다.

- 오류 8개: `tests/fixtures/2026_summer_event`의 `normal_0m.png`,
  `normal_190m.png`, `reward_general.png`, `result_failure.png`가 없어 발생.
  이 fixture 폴더는 이전 HEAD에도 Git에 포함되지 않았다.
- 실패 7개: 실제 현재 시간으로 이벤트 종료 여부를 평가하는 계획 검사.
  이벤트 설정의 종료일은 `2026-08-27T12:00:00+09:00`이므로 STOP을 반환했다.
  테스트에서만 `SummerEventConfig.has_ended=False`로 고정하고 동일한
  실패 검사 7개를 실행하자 모두 통과했다. 앱의 종료일 제한은 변경하지 않았다.

해당 제한을 전체 검사 통과로 보고하지 않는다. 내부 검증 결과는 사용자용
릴리즈 본문에 포함하지 않는다. 빌드 로그는 로컬 `logs/build-v1.5.7.log`에 있다.
