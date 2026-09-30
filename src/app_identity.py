"""Display branding and stable identifiers for existing update clients."""

APP_DISPLAY_NAME = "Epic7 Assist Bot"
APP_SHORT_NAME = "EAB"
APP_WINDOW_TITLE = f"{APP_DISPLAY_NAME} ({APP_SHORT_NAME})"

# Keep these unchanged until legacy clients can migrate to a new package format.
UPDATE_PACKAGE_NAME = "SecretShopBot-E7"
APP_EXECUTABLE = UPDATE_PACKAGE_NAME + ".exe"
UPDATER_EXECUTABLE = "SecretShopBot-Updater.exe"
RELEASE_REPOSITORY = "pelierze/SecretShopBot-E7"


def resolve_window_title(title):
    # Remote/cached settings from older releases must not restore old branding.
    if not title or title == "에픽세븐 비밀상점 자동화":
        return APP_WINDOW_TITLE
    return title
