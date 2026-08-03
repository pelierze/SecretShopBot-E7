import unittest
from unittest.mock import Mock

from src.gui import SessionView


class SessionViewFormattingTest(unittest.TestCase):
    def test_event_stats_show_consumed_drinks(self):
        view = object.__new__(SessionView)
        for attribute in (
            "event_position_label",
            "event_shield_label",
            "event_leap_label",
            "event_super_dash_label",
            "event_attempts_label",
            "event_rollbacks_label",
            "event_drinks_used_label",
            "event_plan_successes_label",
            "event_core_rewards_total_label",
            "event_reward_100_label",
            "event_reward_200_label",
            "event_reward_300_label",
            "event_reward_350_label",
            "event_reward_400_label",
            "event_reward_500_label",
        ):
            setattr(view, attribute, Mock())

        SessionView._update_event_stats(view, {"drinks_used": 17})

        view.event_drinks_used_label.config.assert_called_once_with(text="17개")

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
