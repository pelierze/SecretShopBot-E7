"""Display branding and stable identifiers for existing update clients."""
from pathlib import Path

APP_DISPLAY_NAME = "Epic7 Assist Bot"
APP_SHORT_NAME = "EAB"
APP_WINDOW_TITLE = f"{APP_DISPLAY_NAME} ({APP_SHORT_NAME})"

# Keep these unchanged until legacy clients can migrate to a new package format.
UPDATE_PACKAGE_NAME = "SecretShopBot-E7"
APP_EXECUTABLE = UPDATE_PACKAGE_NAME + ".exe"
UPDATER_EXECUTABLE = "SecretShopBot-Updater.exe"
RELEASE_REPOSITORY = "pelierze/SecretShopBot-E7"
SUPPORTED_RELEASE_REPOSITORIES = (RELEASE_REPOSITORY, "pelierze/EAB")

# Transition clients accept both formats; builds still use the legacy defaults.
SUPPORTED_PACKAGE_NAMES = (UPDATE_PACKAGE_NAME, "EAB")
SUPPORTED_APP_EXECUTABLES = (APP_EXECUTABLE, "EAB.exe")
SUPPORTED_UPDATER_EXECUTABLES = (UPDATER_EXECUTABLE, "EAB-Updater.exe")
UPDATE_MANAGED_FILES = (*SUPPORTED_APP_EXECUTABLES, *SUPPORTED_UPDATER_EXECUTABLES,
                        "_internal", "README.md", "DEPLOY.md", "SECURITY.md",
                        "RELEASE_NOTES.md")


def resolve_executable(directory, names):
    for name in names:
        candidate = Path(directory) / name
        if candidate.is_file():
            return candidate
    raise ValueError("필수 실행 파일 또는 업데이트 프로그램이 없습니다.")


def resolve_app_executable(directory):
    return resolve_executable(directory, SUPPORTED_APP_EXECUTABLES)


def resolve_updater_executable(directory):
    return resolve_executable(directory, SUPPORTED_UPDATER_EXECUTABLES)


def resolve_window_title(title):
    # Remote/cached settings from older releases must not restore old branding.
    if not title or title == "에픽세븐 비밀상점 자동화":
        return APP_WINDOW_TITLE
    return title
