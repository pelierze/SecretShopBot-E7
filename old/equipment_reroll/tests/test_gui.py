import unittest
from unittest.mock import Mock, patch

import tkinter as tk
from tkinter import ttk

from src.gui import SecretShopGUI, SessionView


class ChaosSessionLifecycleTest(unittest.TestCase):
    def test_stop_keeps_session_busy_until_worker_finishes(self):
        view = object.__new__(SessionView)
        view.name = "test"
        view.current_mode = "chaos"
        view.is_running = True
        view.bot = Mock()
        view.chaos_status_label = Mock()
        view.chaos_stop_btn = Mock()
        view.log = Mock()
        view._stop_bot()
        self.assertTrue(view.is_running)
        self.assertTrue(view.was_stopped_by_user)
        view.bot.set_user_action.assert_called_once_with("stop")

    def test_failed_run_restores_controls_without_success_sound(self):
        view = object.__new__(SessionView)
        view.is_running = True
        view._update_chaos_stats = Mock()
        view._set_running_ui = Mock()
        view._play_complete_sound = Mock()
        view._play_stopped_sound = Mock()
        result = {"status": "failed", "phase": "영입 확인", "reason": "시간 초과"}
        view._finish_chaos_run(result)
        self.assertFalse(view.is_running)
        view._set_running_ui.assert_called_once_with(False)
        view._update_chaos_stats.assert_called_once_with(result)
        view._play_complete_sound.assert_not_called()
        view._play_stopped_sound.assert_called_once()

    def test_chaos_start_rejects_a_worker_that_has_not_exited(self):
        view = object.__new__(SessionView)
        view.name = "test"
        view.is_running = False
        view.bot_thread = Mock()
        view.bot_thread.is_alive.return_value = True
        view._start_chaos_bot()
        self.assertFalse(view.is_running)


    @patch("src.gui.ExplorationBot")
    def test_chaos_start_passes_configured_rank_priority(self, mock_exploration_bot):
        view = object.__new__(SessionView)
        view.name = "test"
        view.is_running = False
        view.bot_thread = None
        view.adb_controller = Mock()
        view.runtime_dir = "mock_runtime"
        view.chaos_event_mode = Mock(get=Mock(return_value="ocr"))
        view.chaos_save_unknown = Mock(get=Mock(return_value=False))
        view.chaos_status_label = Mock()
        view._set_running_ui = Mock()
        view._run_chaos_bot = Mock()
        view.root = Mock()

        view.chaos_hero_choices = {
            "knight": ["shadow_rose"],
            "warrior": ["wukong"],
            "soul_weaver": ["destina"],
            "thief": ["jenua"],
        }
        view.chaos_hero_combos = {
            "knight": Mock(current=Mock(return_value=0)),
            "warrior": Mock(current=Mock(return_value=0)),
            "soul_weaver": Mock(current=Mock(return_value=0)),
            "thief": Mock(current=Mock(return_value=0)),
        }
        view.chaos_rank_priority_combos = {
            "knight": Mock(get=Mock(return_value="3순위")),
            "warrior": Mock(get=Mock(return_value="2순위")),
            "soul_weaver": Mock(get=Mock(return_value="제외")),
            "thief": Mock(get=Mock(return_value="1순위")),
        }
        view._start_chaos_bot()
        self.assertTrue(view.is_running)
        mock_exploration_bot.assert_called_once()
        _, kwargs = mock_exploration_bot.call_args
        self.assertEqual(kwargs.get("rank_priority"), ["jenua", "wukong", "shadow_rose"])
        self.assertEqual(kwargs.get("target_clears"), 1)

    @patch("src.gui.ExplorationBot")
    def test_chaos_start_passes_configured_target_clears(self, mock_exploration_bot):
        view = object.__new__(SessionView)
        view.name = "test"
        view.is_running = False
        view.bot_thread = None
        view.adb_controller = Mock()
        view.runtime_dir = "mock_runtime"
        view.chaos_event_mode = Mock(get=Mock(return_value="ocr"))
        view.chaos_save_unknown = Mock(get=Mock(return_value=False))
        view.chaos_status_label = Mock()
        view._set_running_ui = Mock()
        view._run_chaos_bot = Mock()
        view.root = Mock()
        view.chaos_hero_choices = {"knight": ["shadow_rose"], "warrior": ["wukong"], "soul_weaver": ["destina"], "thief": ["jenua"]}
        view.chaos_hero_combos = {k: Mock(current=Mock(return_value=0)) for k in view.chaos_hero_choices}
        view.chaos_target_clears_entry = Mock(get=Mock(return_value="5"))
        view._start_chaos_bot()
        self.assertTrue(view.is_running)
        mock_exploration_bot.assert_called_once()
        _, kwargs = mock_exploration_bot.call_args
        self.assertEqual(kwargs.get("target_clears"), 5)

    @patch("src.gui.ExplorationBot")
    def test_chaos_start_passes_cost_fallback_option(self, mock_exploration_bot):
        view = object.__new__(SessionView)
        view.name = "test"
        view.is_running = False
        view.bot_thread = None
        view.adb_controller = Mock()
        view.runtime_dir = "mock_runtime"
        view.chaos_event_mode = Mock(get=Mock(return_value="ocr"))
        view.chaos_save_unknown = Mock(get=Mock(return_value=False))
        view.chaos_cost_fallback = Mock(get=Mock(return_value=True))
        view.chaos_status_label = Mock()
        view._set_running_ui = Mock()
        view._run_chaos_bot = Mock()
        view.root = Mock()
        view.chaos_hero_choices = {"knight": ["shadow_rose"], "warrior": ["wukong"], "soul_weaver": ["lisette"], "thief": ["rhianna_luciella"]}
        view.chaos_hero_combos = {k: Mock(current=Mock(return_value=0)) for k in view.chaos_hero_choices}
        view.chaos_target_clears_entry = Mock(get=Mock(return_value="1"))
        view._start_chaos_bot()
        self.assertTrue(view.is_running)
        mock_exploration_bot.assert_called_once()
        _, kwargs = mock_exploration_bot.call_args
        self.assertTrue(kwargs.get("auto_fallback"))

    def test_check_chaos_hero_cost_warning(self):
        view = object.__new__(SessionView)
        view.chaos_cost_warning_label = Mock()
        view.chaos_hero_choices = {"knight": ["shadow_rose"], "warrior": ["wukong"], "soul_weaver": ["lisette"], "thief": ["jenua"]}
        view.chaos_hero_combos = {
            "knight": Mock(current=Mock(return_value=0)),
            "warrior": Mock(current=Mock(return_value=0)),
            "soul_weaver": Mock(current=Mock(return_value=0)), # lisette -> high cost
            "thief": Mock(current=Mock(return_value=0)),
        }
        view.chaos_layout = {
            "heroes": {
                "shadow_rose": {"name": "그림자 로제", "cost": "standard"},
                "wukong": {"name": "불사형 오공", "cost": "standard"},
                "lisette": {"name": "리제트", "cost": "high"},
                "jenua": {"name": "제뉴아", "cost": "standard"},
            }
        }
        SessionView._check_chaos_hero_cost_warning(view)
        view.chaos_cost_warning_label.config.assert_called_once()
        _, kwargs = view.chaos_cost_warning_label.config.call_args
        self.assertIn("리제트", kwargs.get("text", ""))
        self.assertIn("고코스트 영웅", kwargs.get("text", ""))

    def test_on_chaos_rank_priority_changed_shifts_former_first_priority(self):
        view = object.__new__(SessionView)
        # Setup: warrior is 1st, thief is 2nd, knight is 3rd, soul_weaver is 제외
        combos = {
            "warrior": Mock(get=Mock(return_value="1순위"), set=Mock()),
            "thief": Mock(get=Mock(return_value="1순위"), set=Mock()), # user just selected 1순위 on thief
            "knight": Mock(get=Mock(return_value="3순위"), set=Mock()),
            "soul_weaver": Mock(get=Mock(return_value="제외"), set=Mock()),
        }
        view.chaos_rank_priority_combos = combos

        # thief was just changed to 1순위
        SessionView._on_chaos_rank_priority_changed(view, "thief")

        # warrior was the existing 1st priority; unassigned priorities among other classes are:
        # taken by others (excluding warrior): thief (1순위), knight (3순위), soul_weaver (제외)
        # highest available: 2순위
        combos["warrior"].set.assert_called_once_with("2순위")

    def test_on_chaos_rank_priority_changed_selects_lowest_unassigned_when_needed(self):
        view = object.__new__(SessionView)
        # Setup: warrior is 1st, thief is 2nd, knight is 3rd, soul_weaver becomes 1st
        combos = {
            "warrior": Mock(get=Mock(return_value="1순위"), set=Mock()),
            "thief": Mock(get=Mock(return_value="2순위"), set=Mock()),
            "knight": Mock(get=Mock(return_value="3순위"), set=Mock()),
            "soul_weaver": Mock(get=Mock(return_value="1순위"), set=Mock()), # user selected 1순위
        }
        view.chaos_rank_priority_combos = combos

        SessionView._on_chaos_rank_priority_changed(view, "soul_weaver")

        # taken by others (excluding warrior): soul_weaver (1순위), thief (2순위), knight (3순위)
        # highest available: 4순위
        combos["warrior"].set.assert_called_once_with("4순위")

    @patch("tkinter.messagebox.showerror")
    @patch("src.gui.ExplorationBot")
    def test_chaos_start_rejects_invalid_target_clears(self, mock_exploration_bot, mock_showerror):
        view = object.__new__(SessionView)
        view.name = "test"
        view.is_running = False
        view.bot_thread = None
        view.adb_controller = Mock()
        view.chaos_hero_choices = {"knight": ["shadow_rose"]}
        view.chaos_hero_combos = {"knight": Mock(current=Mock(return_value=0))}
        view.chaos_target_clears_entry = Mock(get=Mock(return_value="abc"))
        view._start_chaos_bot()
        self.assertFalse(view.is_running)
        mock_exploration_bot.assert_not_called()
        mock_showerror.assert_called_once()


class SessionViewFormattingTest(unittest.TestCase):
    def test_natural_refresh_disables_paid_inputs_and_restores_them(self):
        view = object.__new__(SessionView)
        view.is_running = False
        view.natural_refresh_var = Mock()
        view.refresh_count_entry = Mock()
        view.sky_stone_budget_entry = Mock()
        view._update_macro_dependent_controls = Mock()
        for enabled, expected_state in ((True, "disabled"), (False, "normal")):
            view.natural_refresh_var.get.return_value = enabled
            view._update_natural_refresh_controls()
            view.refresh_count_entry.config.assert_called_with(state=expected_state)
            view.sky_stone_budget_entry.config.assert_called_with(state=expected_state)

    def test_refresh_count_is_converted_to_sky_stones(self):
        self.assertEqual(SessionView._refresh_count_to_sky_stones(100), 300)

    def test_sky_stones_are_converted_to_refresh_count(self):
        self.assertEqual(SessionView._sky_stones_to_refresh_count(6000), 2000)

    def test_sky_stone_remainder_is_discarded(self):
        self.assertEqual(SessionView._sky_stones_to_refresh_count(6002), 2000)

    def test_refresh_count_input_updates_sky_stone_input(self):
        view = object.__new__(SessionView)
        view._shop_input_syncing = False
        view.refresh_count_var = Mock()
        view.refresh_count_var.get.return_value = "100"
        view.sky_stone_budget_var = Mock()

        SessionView._sync_sky_stones_from_refresh_count(view)

        view.sky_stone_budget_var.set.assert_called_once_with("300")
        self.assertFalse(view._shop_input_syncing)

    def test_sky_stone_input_updates_refresh_count_with_floor(self):
        view = object.__new__(SessionView)
        view._shop_input_syncing = False
        view.refresh_count_var = Mock()
        view.sky_stone_budget_var = Mock()
        view.sky_stone_budget_var.get.return_value = "6002"

        SessionView._sync_refresh_count_from_sky_stones(view)

        view.refresh_count_var.set.assert_called_once_with("2000")
        self.assertFalse(view._shop_input_syncing)

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

    def test_reroll_option_label_only_shows_option_name(self):
        view = object.__new__(SessionView)

        self.assertEqual(SessionView._format_reroll_option_label(view, "공격력", True), "공격력")
        self.assertEqual(SessionView._format_reroll_option_label(view, "생명력", False), "생명력")

    def test_reroll_option_name_accepts_legacy_range_label(self):
        view = object.__new__(SessionView)

        self.assertEqual(SessionView._extract_reroll_option_name(view, "방어력 (4~8%)"), "방어력")


class CheckboxIndicatorStyleTest(unittest.TestCase):
    def test_checkbox_custom_indicator_images_and_layout(self):
        root = tk.Tk()
        try:
            app = object.__new__(SecretShopGUI)
            app.root = root
            app.window_icon_image = None
            colors = {
                "bg": "#efe7dc",
                "surface": "#fbf6ee",
                "surface_alt": "#f6efe6",
                "ink": "#2f261f",
                "muted": "#776554",
                "line": "#d8c7b3",
                "accent": "#7a5c3e",
                "accent_hover": "#8c6b4a",
                "accent_soft": "#e8dbc8",
                "success": "#4f6f52",
                "warning": "#b77932",
            }
            indicators = app._create_checkbox_indicators(colors)
            self.assertIn("off", indicators)
            self.assertIn("on", indicators)
            self.assertIn("off_active", indicators)
            self.assertIn("on_active", indicators)

            app._apply_modern_style()
            style = ttk.Style(root)
            layout = style.layout("TCheckbutton")
            self.assertIn("SquareCheck.indicator", str(layout))
        finally:
            root.destroy()


class UpdateLifecycleTest(unittest.TestCase):
    def app(self):
        app = object.__new__(SecretShopGUI)
        app.root = Mock(); app.sessions = []
        app.is_closing = False; app.update_in_progress = True
        app.update_status = Mock(); app.update_progress = Mock(); app.update_window = Mock()
        return app

    def test_download_completion_stops_all_workers_before_launch(self):
        app = self.app()
        session = Mock(); session.is_running = True; session.bot_thread.is_alive.return_value = True
        app.sessions = [session]
        app._finish_app_update = Mock()
        app._app_update_downloaded('plan')
        session.request_stop_for_close.assert_called_once()
        app._finish_app_update.assert_called_once()

    @patch('src.gui.launch_update')
    def test_worker_wait_does_not_close_or_launch_while_bot_active(self, launch):
        app = self.app()
        session = Mock(); session.bot_thread.is_alive.return_value = True; app.sessions = [session]
        app._finish_app_update()
        launch.assert_not_called()
        self.assertFalse(app.is_closing)
        app.root.after.assert_called_once()

    @patch('src.gui.messagebox.showerror')
    def test_failed_preparation_keeps_current_app_usable(self, _message):
        app = self.app()
        app._app_update_failed('network')
        self.assertFalse(app.update_in_progress)
        self.assertFalse(app.is_closing)
        app.root.destroy.assert_not_called()
        app.update_window.destroy.assert_called_once()

    def test_setting_snapshot_includes_nested_hero_selection_and_entries(self):
        root = tk.Tk(); root.withdraw()
        try:
            session = Mock()
            session.flag = tk.BooleanVar(root, False)
            session.chaos_hero_combos = {'knight': ttk.Combobox(root, values=('Rose', 'Other'), state='readonly')}
            session.chaos_hero_combos['knight'].set('Rose')
            session.count = ttk.Entry(root); session.count.insert(0, '2')
            app = self.app(); app.sessions = [session]
            values = [{k: v.get() for k, v in app._update_variables(session)}]
            session.flag.set(True); session.count.delete(0, tk.END)
            session.chaos_hero_combos['knight'].set('Other')
            app._apply_update_settings(values)
            self.assertFalse(session.flag.get())
            self.assertEqual(session.count.get(), '2')
            self.assertEqual(session.chaos_hero_combos['knight'].get(), 'Rose')
        finally: root.destroy()

    @patch('src.gui.UpdateConfirmationDialog')
    def test_declining_update_does_not_start_download(self, prompt):
        from src.release_checker import ReleaseInfo
        app = self.app(); app.update_in_progress = False
        app.release_info = ReleaseInfo('v9.0.0', '', '')
        prompt.return_value.confirmed = False
        with patch('src.gui.sys.frozen', True, create=True), patch('src.gui.release_assets'), patch('src.gui.Path.is_file', return_value=True), patch('src.gui.threading.Thread') as thread:
            app._request_app_update()
        thread.assert_not_called()
        self.assertFalse(app.update_in_progress)
        self.assertIs(prompt.call_args.args[1], app.release_info)

    def test_worker_ack_is_required_before_closing_app(self):
        import tempfile
        from pathlib import Path
        app = self.app(); app.update_worker = Mock(poll=Mock(return_value=None))
        app.update_worker_deadline = float('inf'); app._finish_closing = Mock()
        with tempfile.TemporaryDirectory() as temp:
            app.update_plan = Path(temp) / 'plan.json'
            app._wait_update_worker()
            app._finish_closing.assert_not_called()
            (Path(temp) / 'worker-ready').write_text('ready')
            app._wait_update_worker()
        self.assertTrue(app.is_closing)
        app._finish_closing.assert_called_once()



class RerollSafetySummaryTest(unittest.TestCase):
    def test_safety_stop_summary_includes_reason(self):
        view = object.__new__(SessionView)
        summary = view._format_reroll_summary('장비 리롤 안전 중지', {
            'stop_reason': '옵션 또는 숫자 재확인 불일치', 'goal_achieved': False,
        })
        self.assertIn('중지 사유: 옵션 또는 숫자 재확인 불일치', summary)

    def test_safety_stop_uses_stopped_sound(self):
        view = object.__new__(SessionView)
        view.name = 'test'
        view.root = Mock()
        view.app = Mock(is_closing=False)
        view.bot = Mock()
        view.bot.run.return_value = {'stop_reason': '숫자 재확인 불일치'}
        view.reroll_sound_var = Mock()
        view.reroll_sound_var.get.return_value = True
        view.was_stopped_by_user = False
        view._play_stopped_sound = Mock()
        view._play_complete_sound = Mock()
        view.log = Mock()
        view._run_reroll_bot()
        self.assertIn('안전 중지', view.log.call_args.args[0])
        callbacks = [c.args[1] for c in view.root.after.call_args_list]
        self.assertTrue(any(c is view._play_stopped_sound for c in callbacks))
        self.assertFalse(any(c is view._play_complete_sound for c in callbacks))


if __name__ == '__main__':
    unittest.main()
