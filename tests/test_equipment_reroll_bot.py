import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from src.equipment_reroll_bot import EquipmentRerollBot


class EquipmentRerollBotTest(unittest.TestCase):
    def _make_bot(self):
        bot = object.__new__(EquipmentRerollBot)
        bot.threshold = 0.8
        bot.debug_mode = False
        bot.runtime_dir = Path(".")
        bot.OPTION_PANEL_BOUNDS = EquipmentRerollBot.OPTION_PANEL_BOUNDS
        bot.ROW_COUNT = EquipmentRerollBot.ROW_COUNT
        bot.ROW_VERTICAL_PADDING_RATIO = EquipmentRerollBot.ROW_VERTICAL_PADDING_RATIO
        bot.OPTION_MATCH_WIDTH_RATIO = EquipmentRerollBot.OPTION_MATCH_WIDTH_RATIO
        bot.NUMBER_SCAN_WIDTH_RATIO = EquipmentRerollBot.NUMBER_SCAN_WIDTH_RATIO
        bot.NUMBER_SCAN_HEIGHT_RATIO = EquipmentRerollBot.NUMBER_SCAN_HEIGHT_RATIO
        bot.NUMBER_SCAN_LEFT_GAP_RATIO = EquipmentRerollBot.NUMBER_SCAN_LEFT_GAP_RATIO
        bot.OCR_SCALE = EquipmentRerollBot.OCR_SCALE
        bot.OCR_MIN_CONFIDENCE = EquipmentRerollBot.OCR_MIN_CONFIDENCE
        return bot

    def test_get_row_bounds_splits_right_option_panel_into_four_rows(self):
        bot = self._make_bot()

        rows = bot._get_row_bounds(1280, 720)

        self.assertEqual(len(rows), 4)
        self.assertTrue(all(row[0] < row[2] and row[1] < row[3] for row in rows))
        self.assertTrue(all(rows[index][1] < rows[index + 1][1] for index in range(3)))

    def test_ocr_numeric_image_uses_best_digit_only_result(self):
        bot = self._make_bot()

        class DummyOCR:
            def __call__(self, *args, **kwargs):
                return [["속도", 0.99], ["4", 0.72], ["14", 0.41]], [0.01]

        bot.ocr_engine = DummyOCR()

        value, confidence, has_percent = bot._ocr_numeric_image(np.zeros((20, 20), dtype=np.uint8), use_detection=False)

        self.assertEqual(value, 4)
        self.assertAlmostEqual(confidence, 0.72)
        self.assertFalse(has_percent)

    def test_ocr_numeric_image_detects_percent_suffix(self):
        bot = self._make_bot()

        class DummyOCR:
            def __call__(self, *args, **kwargs):
                return [["5%", 0.81]], [0.01]

        bot.ocr_engine = DummyOCR()

        value, confidence, has_percent = bot._ocr_numeric_image(np.zeros((20, 20), dtype=np.uint8), use_detection=False)

        self.assertEqual(value, 5)
        self.assertAlmostEqual(confidence, 0.81)
        self.assertTrue(has_percent)

    def test_normalize_target_option_supports_added_options(self):
        bot = self._make_bot()

        self.assertEqual(bot._normalize_target_option("공격력"), "attack")
        self.assertEqual(bot._normalize_target_option("생명력"), "life")
        self.assertEqual(bot._normalize_target_option("방어력"), "defense")
        self.assertEqual(bot._normalize_target_option("치명타 확률"), "crit_chance")
        self.assertEqual(bot._normalize_target_option("치명타 피해"), "crit_damage")
        self.assertEqual(bot._normalize_target_option("효과저항"), "effect_resistance")
        self.assertEqual(bot._normalize_target_option("효과적중"), "effectiveness")

    def test_find_target_option_row_matches_only_inside_right_panel_rows(self):
        bot = self._make_bot()
        screen = np.zeros((720, 1280, 3), dtype=np.uint8)
        rows = bot._get_row_bounds(1280, 720)

        template = np.zeros((18, 52, 3), dtype=np.uint8)
        cv2.rectangle(template, (0, 0), (51, 17), (255, 255, 255), -1)
        cv2.circle(template, (10, 9), 5, (0, 0, 0), -1)

        target_row = rows[2]
        row_x1, row_y1, _, _ = target_row
        insert_x = row_x1 + 24
        insert_y = row_y1 + 8
        screen[insert_y:insert_y + template.shape[0], insert_x:insert_x + template.shape[1]] = template

        with tempfile.TemporaryDirectory() as temp_dir:
            template_path = Path(temp_dir) / "speed_option.png"
            success, encoded = cv2.imencode(".png", template)
            self.assertTrue(success)
            encoded.tofile(str(template_path))

            row_index, option_box, row_bounds = bot._find_target_option_row(screen, template_path)

        self.assertEqual(row_index, 2)
        self.assertEqual(row_bounds, target_row)
        self.assertEqual(option_box[:2], (insert_x, insert_y))


if __name__ == "__main__":
    unittest.main()
