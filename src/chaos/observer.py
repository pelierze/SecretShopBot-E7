"""Data-driven observations for exploration hero recruitment."""

import json
from pathlib import Path

import cv2
import numpy as np

from src.image_matcher import read_image
from .theme_selection import ThemeSelectionDetector


class RecruitmentObserver:
    @staticmethod
    def load_config(resource_root):
        return json.loads((Path(resource_root) / "src/chaos/recruitment_layout.json").read_text(encoding="utf-8"))

    def __init__(self, resource_root: Path, hero_ids=None):
        root = Path(resource_root)
        self.config = self.load_config(root)
        if hero_ids is None:
            hero_ids = [self.config["classes"][key]["default_hero"] for key in self.config["class_order"]]
        if not hero_ids or any(key not in self.config["heroes"] for key in hero_ids):
            raise ValueError("지원하지 않는 영웅 구성입니다.")
        self.heroes = [dict(self.config["heroes"][key], id=key) for key in hero_ids]
        if len({hero["class"] for hero in self.heroes}) != len(self.heroes):
            raise ValueError("직업마다 영웅 한 명만 선택할 수 있습니다.")
        self.heroes.sort(key=lambda hero: self.config["class_order"].index(hero["class"]))
        self.assets = root / "images/chaos/hero_selection"
        self.theme = ThemeSelectionDetector(self.assets / "templates/themes")
        self.templates = {}
        sources = {}
        needed = {"start", "unlock", "confirm_theme", "recruit_card", "filter", "filter_panel", "recruit_active", "completed"}
        for element in ("dark", "fire", "ice", "forest", "light"):
            needed.add(element + "_2")
        for hero in self.heroes:
            role = self.config["classes"][hero["class"]]
            needed.update((role["anchor"], role["header"], hero["portrait"], hero["selected"], hero["completed_name"], hero["element"] + "_1"))
            fallback_id = hero.get("fallback") or role.get("default_hero")
            if fallback_id and fallback_id in self.config["heroes"]:
                fb = self.config["heroes"][fallback_id]
                needed.update((fb["portrait"], fb["selected"], fb["completed_name"], fb["element"] + "_1"))
        for name in sorted(needed):
            definition = self.config["markers"][name]
            path = self.assets / definition["file"]
            if path not in sources:
                sources[path] = read_image(str(path))
            source = sources[path]
            if source is None:
                raise ValueError(f"자동 탐사 이미지 누락: {path}")
            if "crop" in definition:
                x, y, w, h = definition["crop"]
                if min(x, y) < 0 or min(w, h) <= 0 or x + w > source.shape[1] or y + h > source.shape[0]:
                    raise ValueError(f"잘못된 원본 이미지 영역: {name}")
                source = source[y:y + h, x:x + w]
            self.templates[name] = source.copy()

    def validate_screen(self, screen):
        if screen is None:
            raise RuntimeError("ADB 화면 이미지를 읽지 못했습니다.")
        if (screen.shape[1], screen.shape[0]) != tuple(self.config["reference_size"]):
            raise RuntimeError("자동 탐사는 1280×720 화면에서 실행해 주세요.")

    def find(self, screen, name, region=None):
        if name not in self.templates:
            return None
        definition = self.config["markers"][name]
        region = region if region is not None else definition.get("region", [0, 0, 1280, 720])
        x, y, w, h = map(int, region)
        if x < 0 or y < 0 or x + w > screen.shape[1] or y + h > screen.shape[0]:
            return None
        template = self.templates[name]
        th, tw = template.shape[:2]
        if h < th or w < tw:
            return None
        sample = screen[y:y + h, x:x + w]
        result = cv2.matchTemplate(sample, template, cv2.TM_CCOEFF_NORMED)
        _, score, _, (mx, my) = cv2.minMaxLoc(result)
        threshold = definition.get("threshold", 0.90)
        if score < threshold:
            return None
        matched = sample[my:my + th, mx:mx + tw]
        error = float(np.abs(matched.astype(np.float32) - template).mean() / 255)
        if error > definition.get("max_color_error", 0.09):
            return None
        # Another independent hit makes the click target ambiguous.
        result[max(0, my - th // 2):my + th // 2 + 1,
               max(0, mx - tw // 2):mx + tw // 2 + 1] = -1
        if float(result.max()) >= threshold:
            return None
        return (x + mx, y + my, tw, th)

    def hero_completed(self, screen, hero):
        slot = self.config["classes"][hero["class"]]["slot"]
        area = (150 + slot * 280, 418, 150, 48)
        if not self.find(screen, "completed", area):
            return False
        completed_marker = hero.get("completed_name")
        if completed_marker and self.find(screen, completed_marker):
            return True
        return self.class_button(screen, hero) is None

    def completed(self, screen):
        return all(self.hero_completed(screen, hero) for hero in self.heroes)

    def class_button(self, screen, hero):
        role = self.config["classes"][hero["class"]]
        anchor = self.find(screen, role["anchor"])
        if not anchor:
            return None
        x, y, w, h = anchor
        dx, dy, rw, rh = self.config["button_offset"]
        return self.find(screen, "recruit_card", (x + w // 2 + dx, y + h // 2 + dy, rw, rh))

    def header(self, screen, hero):
        return self.find(screen, self.config["classes"][hero["class"]]["header"])

    def get_fallback_hero(self, hero):
        fallback_id = hero.get("fallback") or self.config["classes"][hero["class"]].get("default_hero")
        if fallback_id and fallback_id in self.config["heroes"] and fallback_id != hero.get("id"):
            return dict(self.config["heroes"][fallback_id], id=fallback_id)
        return None

    def replace_hero(self, old_hero_id, new_hero):
        for i, h in enumerate(self.heroes):
            if h.get("id") == old_hero_id or h.get("class") == new_hero.get("class"):
                self.heroes[i] = new_hero
                return True
        return False


class KnightObserver(RecruitmentObserver):
    """Keep the independently testable knight milestone available."""
    def __init__(self, resource_root):
        super().__init__(resource_root, ["shadow_rose"])

    def knight_button(self, screen):
        return self.class_button(screen, self.heroes[0])
