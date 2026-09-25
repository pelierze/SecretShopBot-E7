import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from src.chaos.theme_selection import ThemeSelectionDetector


class ThemeSelectionDetectorTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.unselected = np.random.default_rng(4).integers(20, 130, (40, 50, 3), dtype=np.uint8)
        # Identical shape with a brighter background: correlation alone is ambiguous.
        self.selected = self.unselected + 60
        for index, template in enumerate((self.unselected, self.selected), 1):
            cv2.imencode('.png', template)[1].tofile(str(self.directory / f'select_supply_{index}.png'))
        self.detector = ThemeSelectionDetector(self.directory)

    def screen(self, template):
        screen = np.zeros((160, 240, 3), dtype=np.uint8)
        screen[50:90, 80:130] = template
        return screen

    def test_color_distinguishes_states_even_when_both_shapes_match(self):
        for template, expected in ((self.unselected, 'unselected'), (self.selected, 'selected')):
            with self.subTest(state=expected):
                result = self.detector.observe(self.screen(template))
                self.assertGreater(min(result.shape_scores), 0.99)
                self.assertEqual(result.state, expected)
                self.assertEqual(result.bounds, (80, 50, 50, 40))

    def test_transition_color_is_unknown(self):
        result = self.detector.observe(self.screen(self.unselected + 30))
        self.assertEqual(result.state, 'unknown')
        self.assertIsNone(result.bounds)

    def test_small_color_noise_preserves_selection(self):
        result = self.detector.observe(self.screen(self.selected + 3))
        self.assertEqual(result.state, 'selected')

    def test_unrelated_screen_is_unknown(self):
        screen = np.random.default_rng(9).integers(0, 256, (160, 240, 3), dtype=np.uint8)
        self.assertEqual(self.detector.observe(screen).state, 'unknown')

    def test_missing_or_small_capture_is_unknown(self):
        for screen in (None, np.zeros((10, 10, 3), dtype=np.uint8)):
            self.assertEqual(self.detector.observe(screen).state, 'unknown')

    def test_missing_templates_fail_at_initialization(self):
        with self.assertRaises(ValueError):
            ThemeSelectionDetector(self.directory / 'missing')
