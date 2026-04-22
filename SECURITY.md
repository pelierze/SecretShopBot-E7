# 보안 및 백신 오탐 안내

이 프로그램은 Windows용 자동화 도구입니다. 일부 백신 또는 VirusTotal 엔진에서 경고가 표시될 수 있습니다.

## 경고가 표시될 수 있는 이유

- PyInstaller로 패키징한 실행 파일입니다.
- ADB 도구를 포함하거나 실행합니다.
- ADB를 통해 화면 캡처, 터치, 스와이프 명령을 실행합니다.
- 실행 시 GitHub의 원격 JSON 설정 파일을 확인합니다.
- 개인 배포 실행 파일이라 코드 서명 인증서가 적용되어 있지 않습니다.

## 원격 스크립트 정책

앱은 아래 JSON 파일을 확인합니다.

```text
https://raw.githubusercontent.com/pelierze/SecretShopBot-E7/master/remote_script.json
```

이 파일은 JSON 데이터로만 사용됩니다. 원격 Python 코드, 셸 명령, 임의 실행 파일은 다운로드하거나 실행하지 않습니다.

## 무결성 확인

GitHub Release에는 zip 파일과 SHA256 해시를 함께 공개합니다.

다운로드한 zip 파일이 배포자가 올린 파일과 같은지 확인하려면 PowerShell에서 아래 명령을 실행하세요.

```powershell
Get-FileHash -Algorithm SHA256 .\SecretShopBot-E7-v1.0.6.zip
```

출력된 해시가 릴리즈 노트 또는 `.sha256.txt` 파일의 값과 같으면 같은 파일입니다.

## 백신 경고가 있을 때

- GitHub Releases의 공식 배포 파일인지 확인하세요.
- SHA256 해시가 릴리즈 노트와 일치하는지 확인하세요.
- 여러 주요 백신에서 동시에 탐지되는 경우 실행하지 말고 배포자에게 알려주세요.
- 1개 또는 소수 엔진에서만 탐지되는 경우 자동화 도구 특성으로 인한 오탐일 수 있습니다.
