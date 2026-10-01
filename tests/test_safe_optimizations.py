import concurrent.futures
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from src.image_matcher import ImageMatcher, read_image
from src.display.game_area import GameAreaDetector


class SafeTemplateCacheTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.rng = np.random.default_rng(23)
        self.template = self.rng.integers(0, 256, (16, 18, 3), dtype=np.uint8)
        self.path = self.root / '템플릿.png'
        self.screen_path = self.root / '현재화면.png'
        self.write(self.path, self.template)
        self.screen = self.rng.integers(0, 256, (80, 90, 3), dtype=np.uint8)
        self.screen[27:43, 31:49] = self.template
        self.write(self.screen_path, self.screen)

    @staticmethod
    def write(path, image):
        cv2.imencode('.png', image)[1].tofile(str(path))

    def test_all_matching_results_equal_uncached_baseline(self):
        cached = ImageMatcher()
        legacy = ImageMatcher(template_cache_bytes=0)
        for threshold in (0.7, 0.95, 1.01):
            for name in ('find_image', 'find_all_images'):
                self.assertEqual(getattr(cached, name)(self.screen_path, self.path, threshold),
                                 getattr(legacy, name)(self.screen_path, self.path, threshold))
        self.assertEqual(cached.get_similarity(self.screen_path, self.path),
                         legacy.get_similarity(self.screen_path, self.path))
        location = (31, 27, 18, 16)
        self.assertEqual(cached.get_similarity_at_location(self.screen_path, self.path, location),
                         legacy.get_similarity_at_location(self.screen_path, self.path, location))

    def test_template_is_reused_but_latest_screen_is_always_read(self):
        matcher = ImageMatcher()
        with patch('src.image_matcher.read_image', wraps=read_image) as reader:
            self.assertEqual(matcher.find_image(self.screen_path, self.path), (31, 27, 18, 16))
            self.write(self.screen_path, self.rng.integers(0, 256, self.screen.shape, dtype=np.uint8))
            self.assertIsNone(matcher.find_image(self.screen_path, self.path))
        paths = [Path(call.args[0]) for call in reader.call_args_list]
        self.assertEqual(paths.count(self.path), 1)
        self.assertEqual(paths.count(self.screen_path), 2)

    def test_replacement_deletion_and_corruption_never_use_stale_template(self):
        matcher = ImageMatcher()
        matcher._read_template(self.path)
        stamp = self.path.stat().st_mtime_ns
        replacement = self.root / 'new.png'
        updated = self.rng.integers(0, 256, self.template.shape, dtype=np.uint8)
        self.write(replacement, updated)
        os.utime(replacement, ns=(stamp, stamp))
        os.replace(replacement, self.path)
        np.testing.assert_array_equal(matcher._read_template(self.path), updated)
        self.path.unlink()
        self.assertIsNone(matcher._read_template(self.path))
        self.assertEqual(matcher._cached_bytes, 0)
        self.path.write_bytes(b'invalid image')
        self.assertIsNone(matcher._read_template(self.path))
        self.assertEqual(len(matcher._template_cache), 0)

    def test_file_replaced_during_decoding_is_retried(self):
        matcher = ImageMatcher()
        updated = self.rng.integers(0, 256, self.template.shape, dtype=np.uint8)
        attempts = []
        def read_and_replace(path, flags):
            image = read_image(path, flags)
            if not attempts:
                self.write(self.path, updated)
            attempts.append(1)
            return image
        with patch('src.image_matcher.read_image', side_effect=read_and_replace):
            np.testing.assert_array_equal(matcher._read_template(self.path), updated)
        self.assertEqual(len(attempts), 2)

    def test_concurrent_sessions_share_immutable_template_safely(self):
        matcher = ImageMatcher()
        with patch('src.image_matcher.read_image', wraps=read_image) as reader:
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                results = list(executor.map(lambda _: matcher.find_image(self.screen_path, self.path), range(24)))
        self.assertEqual(results, [(31, 27, 18, 16)] * 24)
        self.assertEqual(sum(Path(c.args[0]) == self.path for c in reader.call_args_list), 1)
        self.assertFalse(matcher._read_template(self.path).flags.writeable)

    def test_memory_budget_evicts_and_oversized_template_is_not_retained(self):
        matcher = ImageMatcher(template_cache_bytes=self.template.nbytes)
        matcher._read_template(self.path)
        other = self.root / 'other.png'
        self.write(other, self.template)
        matcher._read_template(other)
        self.assertEqual(len(matcher._template_cache), 1)
        self.assertLessEqual(matcher._cached_bytes, self.template.nbytes)
        matcher.clear_template_cache()
        self.assertEqual(matcher._cached_bytes, 0)
        small = ImageMatcher(template_cache_bytes=1)
        np.testing.assert_array_equal(small._read_template(self.path), self.template)
        self.assertEqual(small._cached_bytes, 0)


class EdgeScanEquivalenceTest(unittest.TestCase):
    @staticmethod
    def legacy(frame):
        h, w = frame.shape[:2]
        if abs(w / h - 16 / 9) < GameAreaDetector.EPSILON:
            return (0, 0, w, h)
        gray = frame if frame.ndim == 2 else np.mean(frame, axis=2)
        if w / h > 16 / 9:
            values = np.mean(gray, axis=0)
            start, end, size = 0, w - 1, w
        else:
            values = np.mean(gray, axis=1)
            start, end, size = 0, h - 1, h
        while start < size // 3 and values[start] < 15:
            start += 1
        while end > 2 * size // 3 and values[end] < 15:
            end -= 1
        extent = end - start + 1
        if extent <= size // 2:
            return GameAreaDetector._calculate_centered_16_9(w, h).rect
        return (start, 0, extent, h) if w / h > 16 / 9 else (0, start, w, extent)

    def test_color_and_gray_borders_thresholds_and_scan_limits(self):
        rng = np.random.default_rng(31)
        for h, w in ((79, 180), (125, 151), (72, 128), (5, 17), (17, 5)):
            for channels in ((), (3,)):
                for level in (0, 14, 15, 16):
                    for border in (0, 1, 31, 32, 33, max(h, w)):
                        frame = rng.integers(60, 256, (h, w) + channels, dtype=np.uint8)
                        if w / h > 16 / 9:
                            frame[:, :border] = level
                            if border:
                                frame[:, -border:] = level
                        else:
                            frame[:border] = level
                            if border:
                                frame[-border:] = level
                        with self.subTest(h=h, w=w, channels=channels, level=level, border=border):
                            self.assertEqual(GameAreaDetector.detect(frame).rect, self.legacy(frame))

    def test_non_contiguous_frame_and_mixed_channels_at_threshold(self):
        frame = np.full((144, 400, 3), [14, 15, 16], dtype=np.uint8)
        frame[:, 80:320] = 150
        view = frame[::2, ::2]
        self.assertEqual(GameAreaDetector.detect(view).rect, self.legacy(view))


if __name__ == '__main__':
    unittest.main()
