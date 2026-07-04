import unittest

from src.gui import SessionView


class SessionViewFormattingTest(unittest.TestCase):
    def test_format_draw_efficiency_returns_decimal_sky_stone_per_draw(self):
        view = object.__new__(SessionView)

        result = SessionView._format_draw_efficiency(view, draw_count=15, sky_stone_usage=8)

        self.assertEqual(result, "1\uBF51\uB2F9 0.53\uAC1C")

    def test_format_draw_efficiency_trims_trailing_zeroes(self):
        view = object.__new__(SessionView)

        result = SessionView._format_draw_efficiency(view, draw_count=2, sky_stone_usage=3)

        self.assertEqual(result, "1\uBF51\uB2F9 1.5\uAC1C")

    def test_format_draw_efficiency_returns_dash_for_empty_values(self):
        view = object.__new__(SessionView)

        self.assertEqual(SessionView._format_draw_efficiency(view, draw_count=0, sky_stone_usage=10), "-")
        self.assertEqual(SessionView._format_draw_efficiency(view, draw_count=5, sky_stone_usage=0), "-")

    def test_reroll_duplicate_key_distinguishes_flat_and_percent_options(self):
        view = object.__new__(SessionView)

        flat_key = SessionView._get_reroll_duplicate_target_key(view, "공격력", False)
        percent_key = SessionView._get_reroll_duplicate_target_key(view, "공격력", True)

        self.assertNotEqual(flat_key, percent_key)
        self.assertEqual(flat_key, ("공격력", False))
        self.assertEqual(percent_key, ("공격력", True))

    def test_reroll_percent_ranges_match_supported_substat_rolls(self):
        view = object.__new__(SessionView)

        for option_name in ("공격력", "생명력", "방어력"):
            self.assertEqual(SessionView._get_reroll_target_range(view, option_name, True), (4, 8))


if __name__ == "__main__":
    unittest.main()
