# SecretShopBot-E7 배포 방법

이 문서는 VSCode에서 Windows 사용자용 배포 zip을 만들고 GitHub Releases에 올리는 절차입니다.

## 1. 배포 zip 만들기

VSCode에서 `Terminal > New Terminal`을 열고 프로젝트 루트에서 실행합니다.

```powershell
.\build_release.ps1 -Version 1.0.5
```

PowerShell 실행 정책 오류가 나오면 아래 명령을 사용합니다.

```powershell
powershell -ExecutionPolicy Bypass -File .\build_release.ps1 -Version 1.0.5
```

성공하면 아래 파일이 생성됩니다.

```text
release/SecretShopBot-E7-v1.0.5.zip
release/SecretShopBot-E7-v1.0.5.zip.sha256.txt
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

- Tag: `v1.0.5`
- Target: `master`
- Release title: `SecretShopBot-E7 v1.0.5`

Release description 예시:

```markdown
## 다운로드 및 실행

1. 아래 Assets에서 `SecretShopBot-E7-v1.0.5.zip`을 다운로드합니다.
2. 압축을 풉니다.
3. `SecretShopBot-E7.exe`를 실행합니다.

## 주의사항

- Windows 전용 배포판입니다.
- ADB를 사용하는 자동화 도구라 Windows SmartScreen 또는 백신 경고가 표시될 수 있습니다.
- 에뮬레이터에서 ADB 디버깅을 켠 뒤 사용하세요.

## SHA256

`release/SecretShopBot-E7-v1.0.5.zip.sha256.txt`의 값을 참고하세요.
```

Assets에는 아래 파일을 첨부합니다.

```text
release/SecretShopBot-E7-v1.0.5.zip
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
