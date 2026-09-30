# SecretShopBot-E7 배포 방법

이 문서는 VSCode에서 Windows 사용자용 배포 zip을 만들고 GitHub Releases에 올리는 절차입니다.

## 1. 배포 zip 만들기

배포 이미지는 `build_support/release_assets.py`에서 코드와 설정 참조를 기준으로 선별합니다. 미사용 원본·스크린샷·템플릿을 폴더째 포함하지 않습니다. 실행 중 목록으로 읽는 금지 품목 및 `class_*.png` 직업 심볼은 포함합니다. 신규 이미지 로딩 방식을 추가하면 이 선별 정책과 `tests/test_release_assets.py`도 함께 갱신하세요. `raw` 안의 이미지라도 실제 설정에서 인식 원본으로 참조하면 배포에 필요합니다.

VSCode에서 `Terminal > New Terminal`을 열고 프로젝트 루트에서 실행합니다.

```powershell
.\build_release.ps1 -Version 1.0.7
```

PowerShell 실행 정책 오류가 나오면 아래 명령을 사용합니다.

```powershell
powershell -ExecutionPolicy Bypass -File .\build_release.ps1 -Version 1.0.7
```

성공하면 아래 파일이 생성됩니다.

```text
release/SecretShopBot-E7-v1.0.7.zip
release/SecretShopBot-E7-v1.0.7.zip.sha256.txt
```

## 2. GitHub에 코드 푸시

변경사항이 있으면 커밋 후 푸시합니다.

```powershell
git status
git add .
git commit -m "chore: add release build workflow"
git push
```

## 3. GitHub Release 생성

브라우저에서 아래 주소를 엽니다.

```text
https://github.com/pelierze/SecretShopBot-E7/releases/new
```

입력값:

- Tag: `v1.0.7`
- Target: `master`
- Release title: `SecretShopBot-E7 v1.0.7`

Release description 예시:

```markdown
## 다운로드 및 실행

1. 아래 Assets에서 `SecretShopBot-E7-v1.0.7.zip`을 다운로드합니다.
2. 압축을 풉니다.
3. `SecretShopBot-E7.exe`를 실행합니다.

## 주의사항

- Windows 전용 배포판입니다.
- ADB를 사용하는 자동화 도구라 Windows SmartScreen 또는 백신 경고가 표시될 수 있습니다.
- 에뮬레이터에서 ADB 디버깅을 켠 뒤 사용하세요.
- VirusTotal에서 소수 엔진만 탐지하는 경우 PyInstaller, ADB, 화면 캡처, 자동 입력 기능으로 인한 오탐일 수 있습니다.

## SHA256

<SHA256-HERE>  SecretShopBot-E7-v1.0.7.zip

PowerShell 확인 명령:

Get-FileHash -Algorithm SHA256 .\SecretShopBot-E7-v1.0.7.zip

`release/SecretShopBot-E7-v1.0.7.zip.sha256.txt`의 값과 비교하세요.
```

Assets에는 아래 파일을 첨부합니다.

```text
release/SecretShopBot-E7-v1.0.7.zip
release/SecretShopBot-E7-v1.0.7.zip.sha256.txt
```

마지막으로 `Publish release`를 누릅니다.

사용자에게는 아래 링크를 안내하면 됩니다.

```text
https://github.com/pelierze/SecretShopBot-E7/releases/latest
```

## 4. 원격 스크립트 동기화 운영

앱은 실행 시 아래 원격 스크립트 파일을 확인합니다.

```text
https://raw.githubusercontent.com/pelierze/SecretShopBot-E7/master/remote_script.json
```

배포자가 `remote_script.json`을 수정해서 `master`에 푸시하면 사용자는 exe를 새로 받지 않아도 다음 실행 시 GUI 표시값과 매크로 동작 정의를 자동으로 적용받습니다.

원격 스크립트로 바꿀 수 있는 값:

- GUI 제목, 섹션명, 버튼명, 라벨명
- 기본 리프레시 횟수
- 구매 완료 검증 횟수
- 이미지별 매칭 정확도
- 스와이프 위치 비율
- 스와이프 시간
- 활성화할 구매 대상 아이템
- 아이템/버튼 이미지 파일명
- 구매/갱신/검증 대기 시간
- 구매 버튼 후보 탐색 기준
- 실행 가능한 매크로 목록
- JSON steps 기반 매크로 동작 순서

주의:

- 원격 스크립트는 JSON 데이터만 사용합니다.
- 원격 Python 코드나 명령은 실행하지 않습니다.
- `schema_version`은 현재 `1`로 유지하세요.
- 임계값은 `70`부터 `99` 사이 정수로 입력하세요.
- 동기화 실패 시 앱은 캐시된 스크립트, 내장 스크립트 순서로 실행됩니다.
- `runner`가 `secret_shop`인 매크로는 exe에 내장된 비밀상점 실행기를 사용합니다.
- `runner`가 `steps`인 매크로는 허용된 JSON 액션만 순서대로 실행합니다.

## 5. 앱 내부 자동 업데이트 배포

자동 업데이트가 포함된 버전을 한 번 수동 설치하면 이후에는 앱의 **업데이트 후 재시작** 버튼으로 설치합니다. `SecretShopBot-Updater.exe`를 앱 EXE 옆에 함께 배포해야 합니다. 태그만 푸시하지 말고 GitHub의 정식 Release에 아래 두 파일을 업로드하세요.

- `SecretShopBot-E7-vX.Y.Z.zip`
- `SecretShopBot-E7-vX.Y.Z.zip.sha256.txt`

ZIP 최상위 폴더는 `SecretShopBot-E7-vX.Y.Z`여야 합니다. `build_release.ps1`이 두 파일을 생성합니다. ZIP에는 EXE 두 개, `_internal`, 배포 문서만 포함합니다. 기존의 미사용 이미지 제외 정책을 유지합니다. 릴리즈 파일을 다시 만들었다면 체크섬도 함께 교체하세요.

앱은 공식 저장소의 정식 릴리즈만 받고 SHA256 검증 후 설치합니다. 다운로드·압축 해제까지 기존 봇은 계속 실행되며, 준비가 끝나면 모든 세션을 중지하고 앱이 종료된 뒤 교체합니다. 새 앱 GUI가 시작됐다는 응답을 확인해야 성공입니다. 재시작 후 봇은 자동 실행하지 않습니다.

설치 폴더 바깥의 같은 드라이브에 임시 폴더를 만들므로 설치 폴더의 상위 경로에도 쓰기 권한이 필요합니다. 일반 사용자 폴더에 압축을 풀어 사용하세요. 준비 단계에서 압축 해제용 여유 공간 2GB를 확인합니다. 관리자 권한 상승은 요청하지 않습니다.

사용자 설정·로그·업데이트 캐시는 유지하고, `_internal`은 통째로 교체해 이전 버전의 미사용 이미지를 남기지 않습니다. 기존 `_internal/logs`와 `_internal/updates`는 따로 보존합니다. UI의 입력값과 선택 옵션도 재시작 시 복원합니다.

다운로드 실패 시 현재 앱은 그대로 유지됩니다. 파일 교체 또는 새 앱 시작 실패 시 이전 파일을 복원하고 재실행합니다. 새 앱의 정상 시작이 확인되면 업데이트 프로그램 종료 후 설치 폴더 옆 `.e7-update-*` 임시 폴더 전체(다운로드, 이전 파일 백업, 임시 실행 파일)를 자동 삭제합니다. 실패한 업데이트는 결과(`result.json`)와 이전 파일(`backup`)을 유지합니다. 실패하여 자동 복구까지 안 되면 안내된 백업 경로를 확인하세요. 정리 프로그램 실행 실패는 업데이트 성공을 취소하지 않으며 `result.json`의 `cleanup_error`에 기록됩니다. 파일 잠금이 계속되거나 정리 중 PC를 종료하면 폴더가 남을 수 있습니다. 기존 업데이트 프로그램을 사용하는 첫 업데이트에는 이전 정리 정책이 적용되며, 새 업데이트 프로그램 설치 후 다음 자동업데이트부터 자동 삭제가 적용됩니다. 전원 종료·디스크 고장처럼 업데이트 프로그램 자체가 중단되는 경우에는 백업을 통한 수동 복구가 필요할 수 있습니다.
