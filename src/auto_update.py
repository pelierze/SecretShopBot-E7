"""
Safe remote settings update support.

This module downloads and validates data-only JSON. It never executes remote
code and only accepts known numeric settings.
"""
import json
import logging
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

from .version import APP_VERSION

logger = logging.getLogger(__name__)

DEFAULT_UPDATE_URL = (
    "https://raw.githubusercontent.com/pelierze/SecretShopBot-E7/master/update_config.json"
)

THRESHOLD_KEYS = {
    "mystic_medal",
    "covenant_bookmark",
    "purchase_button",
    "buy_button",
    "refresh_button",
}


def get_resource_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def get_runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def parse_version(version: str) -> tuple[int, ...]:
    parts = []
    for part in version.split("."):
        try:
            parts.append(int(part))
        except ValueError:
            break
    return tuple(parts)


def clamp_int(value: Any, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise ValueError("boolean is not a valid integer")
    number = int(value)
    if not minimum <= number <= maximum:
        raise ValueError(f"{number} is outside {minimum}-{maximum}")
    return number


def clamp_float(value: Any, minimum: float, maximum: float) -> float:
    if isinstance(value, bool):
        raise ValueError("boolean is not a valid float")
    number = float(value)
    if not minimum <= number <= maximum:
        raise ValueError(f"{number} is outside {minimum}-{maximum}")
    return number


def read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def fetch_json(url: str) -> Dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": f"SecretShopBot-E7/{APP_VERSION}"},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        if response.status != 200:
            raise RuntimeError(f"unexpected status: {response.status}")
        content_type = response.headers.get("Content-Type", "")
        if "text" not in content_type and "json" not in content_type:
            logger.debug("Unexpected update content type: %s", content_type)
        raw = response.read(64 * 1024)
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("remote config must be a JSON object")
    return data


def validate_config(data: Dict[str, Any]) -> Dict[str, Any]:
    if data.get("schema_version") != 1:
        raise ValueError("unsupported update config schema")

    min_version = str(data.get("app_min_version", "0.0.0"))
    if parse_version(APP_VERSION) < parse_version(min_version):
        raise ValueError(f"config requires app {min_version} or newer")

    validated: Dict[str, Any] = {
        "schema_version": 1,
        "config_version": str(data.get("config_version", "unknown")),
        "app_min_version": min_version,
        "defaults": {},
        "thresholds": {},
        "swipe": {},
    }

    defaults = data.get("defaults", {})
    if isinstance(defaults, dict):
        if "refresh_count" in defaults:
            validated["defaults"]["refresh_count"] = clamp_int(defaults["refresh_count"], 1, 10000)
        if "purchase_verification_count" in defaults:
            validated["defaults"]["purchase_verification_count"] = clamp_int(
                defaults["purchase_verification_count"], 1, 20
            )

    thresholds = data.get("thresholds", {})
    if isinstance(thresholds, dict):
        for key in THRESHOLD_KEYS:
            if key in thresholds:
                validated["thresholds"][key] = clamp_int(thresholds[key], 70, 99)

    swipe = data.get("swipe", {})
    if isinstance(swipe, dict):
        if "x_ratio" in swipe:
            validated["swipe"]["x_ratio"] = clamp_float(swipe["x_ratio"], 0.1, 0.95)
        if "start_y_ratio" in swipe:
            validated["swipe"]["start_y_ratio"] = clamp_float(swipe["start_y_ratio"], 0.1, 0.95)
        if "end_y_ratio" in swipe:
            validated["swipe"]["end_y_ratio"] = clamp_float(swipe["end_y_ratio"], 0.05, 0.9)
        if "duration_ms" in swipe:
            validated["swipe"]["duration_ms"] = clamp_int(swipe["duration_ms"], 100, 2000)

    return validated


class SettingsUpdater:
    def __init__(self, update_url: str = DEFAULT_UPDATE_URL):
        self.update_url = update_url
        self.cache_path = get_runtime_root() / "updates" / "update_config_cache.json"
        self.bundled_config_path = get_resource_root() / "update_config.json"

    def load(self) -> tuple[Optional[Dict[str, Any]], str]:
        try:
            remote_data = fetch_json(self.update_url)
            config = validate_config(remote_data)
            self.save_cache(config)
            return config, "remote"
        except Exception as exc:
            logger.info("원격 설정 업데이트를 사용할 수 없습니다: %s", exc)

        cached_data = read_json(self.cache_path)
        if cached_data:
            try:
                return validate_config(cached_data), "cache"
            except Exception as exc:
                logger.info("캐시된 설정을 사용할 수 없습니다: %s", exc)

        bundled_data = read_json(self.bundled_config_path)
        if bundled_data:
            try:
                return validate_config(bundled_data), "bundled"
            except Exception as exc:
                logger.info("내장 설정을 사용할 수 없습니다: %s", exc)

        return None, "default"

    def save_cache(self, config: Dict[str, Any]) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.cache_path.with_suffix(".tmp")
        with temp_path.open("w", encoding="utf-8") as file:
            json.dump(config, file, ensure_ascii=False, indent=2)
        temp_path.replace(self.cache_path)
