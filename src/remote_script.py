"""
Remote JSON script synchronization.

The client downloads data-only JSON that describes GUI text, default settings,
and the supported macro workflow. It never executes remote Python code.
"""
import json
import logging
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

from .version import APP_VERSION

logger = logging.getLogger(__name__)

DEFAULT_SCRIPT_URL = (
    "https://raw.githubusercontent.com/pelierze/SecretShopBot-E7/master/remote_script.json"
)

SAFE_FILENAME = re.compile(r"^[A-Za-z0-9_. -]+$")
SAFE_KEY = re.compile(r"^[A-Za-z0-9_]+$")
ALLOWED_MACRO_RUNNERS = {"secret_shop", "steps"}
ALLOWED_STEP_ACTIONS = {
    "log",
    "wait",
    "screenshot",
    "tap_image",
    "swipe",
    "repeat",
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
    for part in str(version).lstrip("vV").split("."):
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


def safe_text(value: Any, maximum: int = 80) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    return text[:maximum]


def safe_key(value: Any) -> str:
    key = str(value).strip()
    if not SAFE_KEY.match(key):
        raise ValueError(f"invalid key: {key}")
    return key


def safe_filename(value: Any) -> str:
    filename = str(value).strip()
    if "/" in filename or "\\" in filename or ".." in filename or not SAFE_FILENAME.match(filename):
        raise ValueError(f"invalid filename: {filename}")
    return filename


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
        raw = response.read(256 * 1024)
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("remote script must be a JSON object")
    return data


def validate_remote_script(data: Dict[str, Any]) -> Dict[str, Any]:
    if data.get("schema_version") != 1:
        raise ValueError("unsupported remote script schema")

    min_version = str(data.get("app_min_version", "0.0.0"))
    if parse_version(APP_VERSION) < parse_version(min_version):
        raise ValueError(f"remote script requires app {min_version} or newer")

    validated: Dict[str, Any] = {
        "schema_version": 1,
        "script_version": safe_text(data.get("script_version", "unknown"), 40),
        "app_min_version": min_version,
        "gui": {},
        "defaults": {},
        "thresholds": {},
        "swipe": {},
        "macro": {
            "enabled_items": [],
            "items": {},
            "buttons": {},
            "timings": {},
            "thresholds": {},
            "layout": {},
        },
        "macros": [],
    }

    gui = data.get("gui", {})
    if isinstance(gui, dict):
        validated["gui"] = validate_gui(gui)

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
        for key, value in thresholds.items():
            validated["thresholds"][safe_key(key)] = clamp_int(value, 70, 99)

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

    macro = data.get("macro", {})
    if isinstance(macro, dict):
        validated["macro"] = validate_macro(macro)

    macros = data.get("macros", [])
    if isinstance(macros, list):
        validated["macros"] = validate_macros(macros)

    return validated


def validate_gui(gui: Dict[str, Any]) -> Dict[str, Any]:
    validated: Dict[str, Any] = {}
    if "window_title" in gui:
        validated["window_title"] = safe_text(gui["window_title"], 80)

    for section_name in ("sections", "labels", "buttons", "stats"):
        section = gui.get(section_name, {})
        if isinstance(section, dict):
            validated[section_name] = {
                safe_key(key): safe_text(value, 100)
                for key, value in section.items()
            }
    return validated


def validate_macro(macro: Dict[str, Any]) -> Dict[str, Any]:
    validated: Dict[str, Any] = {
        "enabled_items": [],
        "items": {},
        "buttons": {},
        "timings": {},
        "thresholds": {},
        "layout": {},
    }

    items = macro.get("items", {})
    if isinstance(items, dict):
        for raw_key, raw_item in items.items():
            key = safe_key(raw_key)
            if not isinstance(raw_item, dict):
                continue
            validated["items"][key] = {
                "label": safe_text(raw_item.get("label", key), 60),
                "image": safe_filename(raw_item.get("image", f"{key}.png")),
                "stat_key": safe_key(raw_item.get("stat_key", f"{key}_bought")),
                "log_prefix": safe_text(raw_item.get("log_prefix", raw_item.get("label", key)), 60),
            }

    enabled_items = macro.get("enabled_items", [])
    if isinstance(enabled_items, list):
        for item_key in enabled_items:
            key = safe_key(item_key)
            validated["enabled_items"].append(key)

    buttons = macro.get("buttons", {})
    if isinstance(buttons, dict):
        for key in ("refresh", "refresh_confirm", "purchase", "buy", "purchase_disabled"):
            if key in buttons:
                validated["buttons"][key] = safe_filename(buttons[key])

    timings = macro.get("timings", {})
    if isinstance(timings, dict):
        float_ranges = {
            "after_screenshot": (0.0, 3.0),
            "after_scroll": (0.0, 5.0),
            "refresh_confirm_delay": (0.0, 5.0),
            "after_refresh": (0.0, 5.0),
            "refresh_retry": (0.0, 10.0),
            "after_purchase_tap": (0.0, 5.0),
            "buy_button_wait_interval": (0.1, 5.0),
            "verify_interval": (0.0, 5.0),
            "close_popup_delay": (0.0, 5.0),
        }
        for key, limits in float_ranges.items():
            if key in timings:
                validated["timings"][key] = clamp_float(timings[key], *limits)
        if "buy_button_wait_attempts" in timings:
            validated["timings"]["buy_button_wait_attempts"] = clamp_int(
                timings["buy_button_wait_attempts"], 1, 20
            )

    thresholds = macro.get("thresholds", {})
    if isinstance(thresholds, dict):
        if "purchase_candidate" in thresholds:
            validated["thresholds"]["purchase_candidate"] = clamp_int(thresholds["purchase_candidate"], 50, 99)
        if "verification_disabled_button" in thresholds:
            validated["thresholds"]["verification_disabled_button"] = clamp_int(
                thresholds["verification_disabled_button"], 50, 99
            )

    layout = macro.get("layout", {})
    if isinstance(layout, dict) and "purchase_line_y_tolerance" in layout:
        validated["layout"]["purchase_line_y_tolerance"] = clamp_int(
            layout["purchase_line_y_tolerance"], 10, 200
        )

    return validated


def validate_macros(macros: list[Any]) -> list[Dict[str, Any]]:
    validated_macros = []
    seen_ids = set()

    for raw_macro in macros[:50]:
        if not isinstance(raw_macro, dict):
            continue

        macro_id = safe_key(raw_macro.get("id", ""))
        if not macro_id or macro_id in seen_ids:
            continue
        seen_ids.add(macro_id)

        runner = safe_key(raw_macro.get("runner", "steps"))
        if runner not in ALLOWED_MACRO_RUNNERS:
            raise ValueError(f"unsupported macro runner: {runner}")

        validated = {
            "id": macro_id,
            "name": safe_text(raw_macro.get("name", macro_id), 80),
            "description": safe_text(raw_macro.get("description", ""), 160),
            "runner": runner,
            "steps": [],
        }

        steps = raw_macro.get("steps", [])
        if runner == "steps":
            if not isinstance(steps, list) or not steps:
                raise ValueError(f"macro {macro_id} has no steps")
            validated["steps"] = validate_steps(steps)
        elif isinstance(steps, list):
            validated["steps"] = validate_steps(steps)

        validated_macros.append(validated)

    return validated_macros


def validate_steps(steps: list[Any], depth: int = 0) -> list[Dict[str, Any]]:
    if depth > 3:
        raise ValueError("step nesting is too deep")

    validated_steps = []
    for raw_step in steps[:500]:
        if not isinstance(raw_step, dict):
            continue

        action = safe_key(raw_step.get("action", ""))
        if action not in ALLOWED_STEP_ACTIONS:
            raise ValueError(f"unsupported step action: {action}")

        step: Dict[str, Any] = {"action": action}

        if "message" in raw_step:
            step["message"] = safe_text(raw_step["message"], 200)
        if "target" in raw_step:
            step["target"] = safe_key(raw_step["target"])
        if "target_type" in raw_step:
            target_type = safe_key(raw_step["target_type"])
            if target_type not in {"button", "item"}:
                raise ValueError(f"unsupported target type: {target_type}")
            step["target_type"] = target_type
        if "image" in raw_step:
            step["image"] = safe_filename(raw_step["image"])
        if "required" in raw_step:
            step["required"] = bool(raw_step["required"])
        if "threshold" in raw_step:
            step["threshold"] = clamp_int(raw_step["threshold"], 50, 99)
        if "seconds" in raw_step:
            step["seconds"] = clamp_float(raw_step["seconds"], 0.0, 60.0)
        if "duration_ms" in raw_step:
            step["duration_ms"] = clamp_int(raw_step["duration_ms"], 100, 5000)
        if "count" in raw_step:
            step["count"] = clamp_int(raw_step["count"], 1, 10000)

        for ratio_key in ("x_ratio", "start_y_ratio", "end_y_ratio"):
            if ratio_key in raw_step:
                step[ratio_key] = clamp_float(raw_step[ratio_key], 0.0, 1.0)

        if action == "repeat":
            nested_steps = raw_step.get("steps", [])
            if not isinstance(nested_steps, list) or not nested_steps:
                raise ValueError("repeat step requires nested steps")
            step["steps"] = validate_steps(nested_steps, depth + 1)

        validated_steps.append(step)

    return validated_steps


class RemoteScriptUpdater:
    def __init__(self, script_url: str = DEFAULT_SCRIPT_URL):
        self.script_url = script_url
        self.cache_path = get_runtime_root() / "updates" / "remote_script_cache.json"
        self.bundled_script_path = get_resource_root() / "remote_script.json"

    def load(self) -> tuple[Optional[Dict[str, Any]], str]:
        try:
            remote_data = fetch_json(self.script_url)
            script = validate_remote_script(remote_data)
            try:
                self.save_cache(script)
            except Exception as exc:
                logger.info("원격 스크립트 캐시 저장에 실패했습니다: %s", exc)
            return script, "remote"
        except Exception as exc:
            logger.info("원격 스크립트 동기화를 사용할 수 없습니다: %s", exc)

        cached_data = read_json(self.cache_path)
        if cached_data:
            try:
                return validate_remote_script(cached_data), "cache"
            except Exception as exc:
                logger.info("캐시된 스크립트를 사용할 수 없습니다: %s", exc)

        bundled_data = read_json(self.bundled_script_path)
        if bundled_data:
            try:
                return validate_remote_script(bundled_data), "bundled"
            except Exception as exc:
                logger.info("내장 스크립트를 사용할 수 없습니다: %s", exc)

        return None, "default"

    def save_cache(self, script: Dict[str, Any]) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.cache_path.with_suffix(".tmp")
        with temp_path.open("w", encoding="utf-8") as file:
            json.dump(script, file, ensure_ascii=False, indent=2)
        temp_path.replace(self.cache_path)
