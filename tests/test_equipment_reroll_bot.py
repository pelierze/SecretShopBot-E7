import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

import src.equipment_reroll_bot as equipment_module
from src.equipment_reroll_bot import EquipmentRerollBot


class EquipmentRerollBotTest(unittest.TestCase):
    def _make_bot(self):
        bot = object.__new__(EquipmentRerollBot)
        bot.threshold = 0.8
        bot.debug_mode = False
        bot.runtime_dir = Path(".")
        bot.target_mode = EquipmentRerollBot.TARGET_MODE_EXACT
        bot.required_match_count = 1
        bot.OPTION_PANEL_BOUNDS = EquipmentRerollBot.OPTION_PANEL_BOUNDS
        bot.option_panel_bounds = dict(EquipmentRerollBot.OPTION_PANEL_BOUNDS)
        bot.ROW_COUNT = EquipmentRerollBot.ROW_COUNT
        bot.ROW_VERTICAL_PADDING_RATIO = EquipmentRerollBot.ROW_VERTICAL_PADDING_RATIO
        bot.OPTION_MATCH_WIDTH_RATIO = EquipmentRerollBot.OPTION_MATCH_WIDTH_RATIO
        bot.OPTION_MATCH_VERTICAL_MARGIN_RATIO = EquipmentRerollBot.OPTION_MATCH_VERTICAL_MARGIN_RATIO
        bot.OPTION_RECOGNITION_RETRY_COUNT = EquipmentRerollBot.OPTION_RECOGNITION_RETRY_COUNT
        bot.NUMBER_SCAN_WIDTH_RATIO = EquipmentRerollBot.NUMBER_SCAN_WIDTH_RATIO
        bot.NUMBER_SCAN_HEIGHT_RATIO = EquipmentRerollBot.NUMBER_SCAN_HEIGHT_RATIO
        bot.NUMBER_SCAN_LEFT_GAP_RATIO = EquipmentRerollBot.NUMBER_SCAN_LEFT_GAP_RATIO
        bot.OCR_SCALE = EquipmentRerollBot.OCR_SCALE
        bot.OCR_MIN_CONFIDENCE = EquipmentRerollBot.OCR_MIN_CONFIDENCE
        bot.OCR_FOREGROUND_MIN_PIXELS = EquipmentRerollBot.OCR_FOREGROUND_MIN_PIXELS
        bot.OCR_FOREGROUND_PADDING = EquipmentRerollBot.OCR_FOREGROUND_PADDING
        bot.OCR_ONE_MAX_WIDTH_RATIO = EquipmentRerollBot.OCR_ONE_MAX_WIDTH_RATIO
        bot.REROLL_BUTTON_RETRY_COUNT = EquipmentRerollBot.REROLL_BUTTON_RETRY_COUNT
        bot.locked_option_count = 0
        bot.locked_rows = []
        return bot

    def test_get_row_bounds_splits_right_option_panel_into_four_rows(self):
        bot = self._make_bot()

        rows = bot._get_row_bounds(1280, 720)

        self.assertEqual(len(rows), 4)
        self.assertTrue(all(row[0] < row[2] and row[1] < row[3] for row in rows))
        self.assertTrue(all(rows[index][1] < rows[index + 1][1] for index in range(3)))
        self.assertEqual(rows[0], (558, 186, 828, 232))
        self.assertEqual(rows[1], (558, 233, 828, 279))
        self.assertEqual(rows[2], (558, 280, 828, 326))
        self.assertEqual(rows[3], (558, 327, 828, 373))

    def test_normalize_option_panel_bounds_accepts_custom_selection(self):
        bot = self._make_bot()

        bounds = bot._normalize_option_panel_bounds({"left": 0.2, "top": 0.3, "right": 0.8, "bottom": 0.9})

        self.assertEqual(bounds, {"left": 0.2, "top": 0.3, "right": 0.8, "bottom": 0.9})

    def test_normalize_option_panel_bounds_falls_back_on_invalid_order(self):
        bot = self._make_bot()

        bounds = bot._normalize_option_panel_bounds({"left": 0.7, "top": 0.3, "right": 0.2, "bottom": 0.9})

        self.assertEqual(bounds, EquipmentRerollBot.OPTION_PANEL_BOUNDS)

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

    def test_initialize_ocr_engine_reports_startup_error(self):
        bot = self._make_bot()
        bot.ocr_engine = None

        def raise_startup_error():
            raise FileNotFoundError("missing rapidocr resource")

        with patch.object(equipment_module, "RapidOCR", raise_startup_error):
            with patch.object(equipment_module, "RAPIDOCR_IMPORT_ERROR", None):
                ready = bot._initialize_ocr_engine()

        self.assertFalse(ready)
        self.assertIsNone(bot.ocr_engine)
        self.assertIn("OCR 엔진을 초기화할 수 없습니다", bot.get_startup_error())
        self.assertIn("missing rapidocr resource", bot.get_startup_error())

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

    def test_select_best_numeric_candidate_prefers_consensus(self):
        bot = self._make_bot()

        candidate, has_percent, confidence = bot._select_best_numeric_candidate(
            {
                (8, True): {"count": 3.0, "confidence_sum": 1.71, "best_confidence": 0.58},
                (6, True): {"count": 1.0, "confidence_sum": 0.84, "best_confidence": 0.84},
            }
        )

        self.assertEqual(candidate, 8)
        self.assertTrue(has_percent)
        self.assertAlmostEqual(confidence, 0.58)

    def test_select_best_numeric_candidate_penalizes_one_for_eight_like_shape(self):
        bot = self._make_bot()

        candidate, has_percent, confidence = bot._select_best_numeric_candidate(
            {
                (1, True): {"count": 2.0, "confidence_sum": 1.40, "best_confidence": 0.72},
                (8, True): {"count": 2.0, "confidence_sum": 1.32, "best_confidence": 0.68},
            },
            {"width_ratio": 0.62, "hole_count": 2.0},
        )

        self.assertEqual(candidate, 8)
        self.assertTrue(has_percent)
        self.assertAlmostEqual(confidence, 0.68)

    def test_crop_numeric_foreground_trims_wide_empty_margins(self):
        bot = self._make_bot()
        image = np.zeros((30, 120), dtype=np.uint8)
        cv2.putText(image, "8", (45, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.8, 255, 2, cv2.LINE_AA)

        cropped = bot._crop_numeric_foreground(image)

        self.assertLess(cropped.shape[1], image.shape[1])
        self.assertGreater(cropped.shape[0], 0)

    def test_is_value_in_expected_range_rejects_invalid_defense_percent(self):
        bot = self._make_bot()

        self.assertFalse(bot._is_value_in_expected_range("defense", 1, True))
        self.assertTrue(bot._is_value_in_expected_range("defense", 8, True))

    def test_read_row_numeric_value_retries_when_candidate_is_out_of_range(self):
        bot = self._make_bot()
        screen = np.zeros((60, 160, 3), dtype=np.uint8)

        def fake_build_variants(_number_roi, scale_multiplier=1.0):
            if scale_multiplier > 1.0:
                return [("retry", np.zeros((10, 10), dtype=np.uint8))]
            return [("primary", np.zeros((10, 10), dtype=np.uint8))]

        def fake_collect(processed_images):
            variant_name = processed_images[0][0]
            if variant_name == "primary":
                return {(1, True): {"count": 2.0, "confidence_sum": 1.4, "best_confidence": 0.72}}
            return {(8, True): {"count": 2.0, "confidence_sum": 1.3, "best_confidence": 0.67}}

        bot._build_ocr_variants = fake_build_variants
        bot._collect_numeric_candidate_scores = fake_collect
        bot._analyze_numeric_shape = lambda _roi: None

        value, has_percent = bot._read_row_numeric_value(screen, (0, 0, 160, 60), (0, 0, 20, 20), 0, "defense")

        self.assertEqual(value, 8)
        self.assertTrue(has_percent)

    def test_read_row_numeric_value_uses_option_box_center_even_if_box_is_above_row_bounds(self):
        bot = self._make_bot()
        screen = np.zeros((400, 160, 3), dtype=np.uint8)
        captured_roi_heights = []

        def fake_build_variants(number_roi, scale_multiplier=1.0):
            captured_roi_heights.append(number_roi.shape[0])
            return []

        bot._build_ocr_variants = fake_build_variants
        bot._collect_numeric_candidate_scores = lambda _processed_images: {}
        bot._analyze_numeric_shape = lambda _roi: None

        value, has_percent = bot._read_row_numeric_value(screen, (0, 304, 160, 356), (0, 293, 30, 18), 2, "speed")

        self.assertIsNone(value)
        self.assertFalse(has_percent)
        self.assertGreaterEqual(captured_roi_heights[0], 28)

    def test_scan_target_rows_once_skips_numeric_ocr_for_non_target_options(self):
        bot = self._make_bot()
        bot.target_specs = [{"option": "speed", "value": 4, "is_percent": False}]
        bot._get_row_bounds = lambda _width, _height: [(0, 0, 100, 20)]
        bot._find_best_target_option_in_row = lambda *_args, **_kwargs: {
            "option": "attack",
            "box": (10, 2, 30, 10),
            "similarity": 0.92,
        }
        bot._read_row_numeric_value = lambda *_args, **_kwargs: self.fail("numeric OCR should not run for non-target rows")

        results = bot._scan_target_rows_once(
            np.zeros((50, 120, 3), dtype=np.uint8),
            {"attack": np.zeros((10, 10, 3), dtype=np.uint8)},
            read_numeric=True,
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["option"], "attack")
        self.assertIsNone(results[0]["value"])

    def test_scan_target_rows_retries_when_option_count_is_short(self):
        bot = self._make_bot()
        bot.locked_option_count = 2
        bot.target_specs = [{"option": "speed", "value": 4, "is_percent": False}]
        bot.OPTION_RECOGNITION_RETRY_COUNT = 1
        scan_results = [
            [{"row_index": 0, "option": "speed", "box": (0, 0, 10, 10), "value": 4, "is_percent": False, "similarity": 0.91}],
            [
                {"row_index": 0, "option": "speed", "box": (0, 0, 10, 10), "value": 4, "is_percent": False, "similarity": 0.91},
                {"row_index": 1, "option": "attack", "box": (0, 20, 10, 10), "value": None, "is_percent": True, "similarity": 0.88},
            ],
        ]
        calls = []

        def fake_scan_once(_screen, _templates, _read_numeric, vertical_margin_multiplier=1.0, threshold_override=None):
            calls.append((vertical_margin_multiplier, threshold_override))
            return scan_results[len(calls) - 1]

        bot._scan_target_rows_once = fake_scan_once

        with patch.object(equipment_module, "read_image", return_value=np.zeros((10, 10, 3), dtype=np.uint8)):
            results = bot._scan_target_rows(
                np.zeros((60, 120, 3), dtype=np.uint8),
                {"option:speed": Path("speed.png"), "option:attack": Path("attack.png")},
                read_numeric=True,
            )

        self.assertEqual(len(calls), 2)
        self.assertEqual(len(results), 2)
        self.assertEqual(sorted(row["row_index"] for row in results), [0, 1])

    def test_should_retry_option_recognition_when_target_hits_are_short(self):
        bot = self._make_bot()
        bot.locked_rows = [0, 3]
        bot.target_specs = [
            {"option": "life", "value": 180, "is_percent": False},
            {"option": "speed", "value": 2, "is_percent": False},
        ]

        should_retry = bot._should_retry_option_recognition(
            [
                {"row_index": 1, "option": "life", "value": None, "is_percent": False},
                {"row_index": 2, "option": "crit_damage", "value": None, "is_percent": True},
            ]
        )

        self.assertTrue(should_retry)

    def test_scan_target_rows_once_skips_user_locked_rows(self):
        bot = self._make_bot()
        bot.locked_rows = [0, 2]
        bot.target_specs = [{"option": "speed", "value": 4, "is_percent": False}]
        bot._get_row_bounds = lambda _width, _height: [(0, 0, 100, 20), (0, 20, 100, 40), (0, 40, 100, 60), (0, 60, 100, 80)]
        seen_rows = []

        def fake_find(_screen, _bounds, _templates, row_index, **_kwargs):
            seen_rows.append(row_index)
            return {"option": "speed", "box": (10, row_index * 10, 30, 10), "similarity": 0.9}

        bot._find_best_target_option_in_row = fake_find
        bot._read_row_numeric_value = lambda *_args, **_kwargs: (4, False)

        results = bot._scan_target_rows_once(
            np.zeros((100, 120, 3), dtype=np.uint8),
            {"speed": np.zeros((10, 10, 3), dtype=np.uint8)},
            read_numeric=True,
        )

        self.assertEqual(seen_rows, [1, 3])
        self.assertEqual([row["row_index"] for row in results], [1, 3])

    def test_scan_target_rows_once_prefers_target_templates_before_fallback(self):
        bot = self._make_bot()
        bot.locked_rows = []
        bot.target_specs = [{"option": "speed", "value": 4, "is_percent": False}]
        bot._get_row_bounds = lambda _width, _height: [(0, 0, 100, 20)]
        call_order = []

        def fake_find(_screen, _bounds, templates, _row_index, **_kwargs):
            call_order.append(sorted(templates.keys()))
            if "speed" in templates:
                return {"option": "speed", "box": (10, 2, 30, 10), "similarity": 0.91}
            return {"option": "crit_damage", "box": (12, 3, 30, 10), "similarity": 0.99}

        bot._find_best_target_option_in_row = fake_find
        bot._read_row_numeric_value = lambda *_args, **_kwargs: (4, False)

        results = bot._scan_target_rows_once(
            np.zeros((50, 120, 3), dtype=np.uint8),
            {
                "speed": np.zeros((10, 10, 3), dtype=np.uint8),
                "crit_damage": np.zeros((10, 10, 3), dtype=np.uint8),
            },
            read_numeric=True,
        )

        self.assertEqual(call_order, [["speed"]])
        self.assertEqual(results[0]["option"], "speed")

    def test_normalize_target_option_supports_added_options(self):
        bot = self._make_bot()

        self.assertEqual(bot._normalize_target_option("공격력"), "attack")
        self.assertEqual(bot._normalize_target_option("생명력"), "life")
        self.assertEqual(bot._normalize_target_option("방어력"), "defense")
        self.assertEqual(bot._normalize_target_option("치명타 확률"), "crit_chance")
        self.assertEqual(bot._normalize_target_option("치명타 피해"), "crit_damage")
        self.assertEqual(bot._normalize_target_option("효과저항"), "effect_resistance")
        self.assertEqual(bot._normalize_target_option("효과적중"), "effectiveness")

    def test_evaluate_target_matches_counts_exact_matches(self):
        bot = self._make_bot()
        bot.target_mode = EquipmentRerollBot.TARGET_MODE_EXACT
        bot.target_specs = [
            {"option": "speed", "value": 4, "is_percent": False},
            {"option": "attack", "value": 5, "is_percent": True},
        ]

        row_results = [
            {"row_index": 0, "option": "speed", "value": 4, "is_percent": False},
            {"row_index": 1, "option": "attack", "value": 5, "is_percent": True},
        ]

        option_count, target_count, exact_matches, ocr_failure, success = bot._evaluate_target_matches(row_results)

        self.assertEqual(option_count, 2)
        self.assertEqual(target_count, 2)
        self.assertEqual(len(exact_matches), 2)
        self.assertIsNone(ocr_failure)
        self.assertTrue(success)

    def test_evaluate_target_matches_reports_ocr_failure_on_exact_match(self):
        bot = self._make_bot()
        bot.target_mode = EquipmentRerollBot.TARGET_MODE_EXACT
        bot.target_specs = [{"option": "speed", "value": 4, "is_percent": False}]

        row_results = [{"row_index": 0, "option": "speed", "value": None, "is_percent": False}]

        option_count, target_count, exact_matches, ocr_failure, success = bot._evaluate_target_matches(row_results)

        self.assertEqual(option_count, 1)
        self.assertEqual(target_count, 0)
        self.assertEqual(exact_matches, [])
        self.assertEqual(ocr_failure["option"], "speed")
        self.assertFalse(success)

    def test_evaluate_target_matches_counts_exact_value_matches_in_count_mode(self):
        bot = self._make_bot()
        bot.target_mode = EquipmentRerollBot.TARGET_MODE_COUNT
        bot.required_match_count = 2
        bot.target_specs = [
            {"option": "speed", "value": 4, "is_percent": False},
            {"option": "attack", "value": 8, "is_percent": True},
            {"option": "life", "value": 8, "is_percent": True},
        ]

        row_results = [
            {"row_index": 0, "option": "speed", "value": 4, "is_percent": False},
            {"row_index": 1, "option": "attack", "value": 6, "is_percent": True},
            {"row_index": 2, "option": "life", "value": 8, "is_percent": True},
        ]

        option_count, target_count, matched_specs, ocr_failure, success = bot._evaluate_target_matches(row_results)

        self.assertEqual(option_count, 3)
        self.assertEqual(target_count, 2)
        self.assertEqual([spec["option"] for spec in matched_specs], ["speed", "life"])
        self.assertIsNone(ocr_failure)
        self.assertTrue(success)

    def test_evaluate_target_matches_reports_ocr_failure_on_count_mode(self):
        bot = self._make_bot()
        bot.target_mode = EquipmentRerollBot.TARGET_MODE_COUNT
        bot.required_match_count = 1
        bot.target_specs = [{"option": "speed", "value": 4, "is_percent": False}]

        row_results = [{"row_index": 0, "option": "speed", "value": None, "is_percent": False}]

        option_count, target_count, matched_specs, ocr_failure, success = bot._evaluate_target_matches(row_results)

        self.assertEqual(option_count, 1)
        self.assertEqual(target_count, 0)
        self.assertEqual(matched_specs, [])
        self.assertEqual(ocr_failure["option"], "speed")
        self.assertFalse(success)

    def test_click_image_with_retry_retries_until_success(self):
        bot = self._make_bot()
        attempts = []

        def fake_click(_image_path, _label):
            attempts.append(1)
            return len(attempts) == 3

        bot._click_image = fake_click
        bot._sleep_with_stop = lambda _seconds: True

        success = bot._click_image_with_retry(Path("dummy.png"), "버튼", retries=3)

        self.assertTrue(success)
        self.assertEqual(len(attempts), 3)

    def test_find_best_target_option_in_row_matches_target_template(self):
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

        result = bot._find_best_target_option_in_row(screen, target_row, {"speed": template}, row_index=2)

        self.assertEqual(result["option"], "speed")
        self.assertEqual(result["box"][:2], (insert_x, insert_y))


if __name__ == "__main__":
    unittest.main()
