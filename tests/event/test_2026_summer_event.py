import importlib
import json
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from src.event import (
    EventAction,
    EventPlan,
    EventState,
    ItemInventory,
    MoveOutcome,
    load_event_module,
)
from src.event.ports import EventInputError, EventOutcomePending, EventRecognitionError


event_module = importlib.import_module("src.event.events.2026_summer_event")
policy_module = importlib.import_module("src.event.events.2026_summer_event.policy")
bot_module = importlib.import_module("src.event.events.2026_summer_event.bot")
observer_module = importlib.import_module("src.event.events.2026_summer_event.observer")
SummerEventConfig = event_module.SummerEventConfig
SummerEventPolicy = event_module.SummerEventPolicy
SummerEventRules = event_module.SummerEventRules
load_config = event_module.load_config
load_event_bundle = event_module.load_event_bundle
load_generated_policy = event_module.load_generated_policy
load_probability_data = event_module.load_probability_data
load_screen_layout = event_module.load_screen_layout
derive_linear_probabilities = event_module.derive_linear_probabilities
MissingProbabilityData = policy_module.MissingProbabilityData
SummerEventPlanner = event_module.SummerEventPlanner
PlannedSummerEventPolicy = event_module.PlannedSummerEventPolicy
SummerEventExecutor = event_module.SummerEventExecutor
SummerEventObserver = event_module.SummerEventObserver
EventScreenKind = event_module.EventScreenKind
ObservedEventScreen = event_module.ObservedEventScreen
UnknownTileProbabilityRecorder = event_module.UnknownTileProbabilityRecorder
AdaptiveProbabilityModel = event_module.AdaptiveProbabilityModel


class SummerEventRulesTest(unittest.TestCase):
    def setUp(self):
        self.rules = SummerEventRules()

    def test_registry_loads_numeric_event_package(self):
        module = load_event_module("2026_summer_event")

        self.assertEqual(module.EVENT_ID, "2026_summer_event")

    def test_actions_use_in_game_display_names(self):
        self.assertEqual(EventAction.BASIC.display_name, "달리기")
        self.assertEqual(EventAction.SHIELD.display_name, "보호")
        self.assertEqual(EventAction.LEAP.display_name, "도움닫기")
        self.assertEqual(EventAction.SUPER_DASH.display_name, "슈퍼럭키")

    def test_basic_failure_rolls_back_and_preserves_rewards(self):
        state = EventState(
            position_m=190,
            items=ItemInventory(shield=0, leap=0, super_dash=0),
            collected_reward_tiles={100},
        )

        self.rules.apply(state, EventAction.BASIC, MoveOutcome.FAILURE)

        self.assertEqual(state.position_m, 0)
        self.assertEqual(state.collected_reward_tiles, {100})
        self.assertEqual(state.stats.rollbacks, 1)
        self.assertEqual(state.stats.drinks_used, 1)
        self.assertEqual(state.items, ItemInventory(shield=2, leap=1, super_dash=2))

    def test_shield_is_consumed_on_success(self):
        state = EventState(position_m=20, items=ItemInventory(shield=2))

        self.rules.apply(state, EventAction.SHIELD, MoveOutcome.SUCCESS)

        self.assertEqual(state.position_m, 30)
        self.assertEqual(state.items.shield, 1)

    def test_shield_failure_stays_in_place_and_consumes_stack(self):
        state = EventState(position_m=90, items=ItemInventory(shield=1))

        self.rules.apply(state, EventAction.SHIELD, MoveOutcome.FAILURE)

        self.assertEqual(state.position_m, 90)
        self.assertEqual(state.items.shield, 0)
        self.assertEqual(state.stats.rollbacks, 0)

    def test_leap_collects_every_crossed_reward(self):
        state = EventState(position_m=290, items=ItemInventory(leap=1))

        self.rules.apply(state, EventAction.LEAP, MoveOutcome.SUCCESS)

        self.assertEqual(state.position_m, 320)
        self.assertEqual(state.stats.rewards, {300: 1})
        self.assertEqual(state.items.leap, 1)
        self.assertEqual(state.stats.drinks_used, 1)

    def test_reward_can_be_collected_again_after_rollback(self):
        state = EventState(position_m=90)
        self.rules.apply(state, EventAction.BASIC, MoveOutcome.SUCCESS)
        state.position_m = 90

        self.rules.apply(state, EventAction.BASIC, MoveOutcome.SUCCESS)

        self.assertEqual(state.stats.rewards[100], 2)

    def test_super_dash_is_guaranteed_and_costs_three_drinks(self):
        state = EventState(position_m=330, items=ItemInventory(super_dash=1))

        self.rules.apply(state, EventAction.SUPER_DASH, MoveOutcome.SUCCESS)

        self.assertEqual(state.position_m, 360)
        self.assertEqual(state.stats.rewards, {350: 1})
        self.assertEqual(state.items.super_dash, 0)
        self.assertEqual(state.stats.drinks_used, 3)

    def test_leap_uses_previous_tile_probability(self):
        self.assertEqual(self.rules.probability_tile(100, EventAction.LEAP), 90)
        self.assertEqual(self.rules.probability_tile(0, EventAction.LEAP), 0)

    def test_leap_observation_is_mapped_to_current_displayed_position(self):
        self.assertEqual(self.rules.observation_tile(100, EventAction.LEAP), 100)
        self.assertEqual(self.rules.observation_tile(60, EventAction.LEAP), 60)

    def test_leap_from_100m_uses_90m_probability_and_finishes_at_130m(self):
        state = EventState(position_m=100, items=ItemInventory(leap=1))

        probability_tile = self.rules.probability_tile(state.position_m, EventAction.LEAP)
        self.rules.apply(state, EventAction.LEAP, MoveOutcome.SUCCESS)

        self.assertEqual(probability_tile, 90)
        self.assertEqual(state.position_m, 130)

    def test_crossing_100m_recharges_shield_and_leap_to_caps(self):
        state = EventState(
            position_m=90,
            items=ItemInventory(shield=3, leap=2, super_dash=0),
        )

        self.rules.apply(state, EventAction.BASIC, MoveOutcome.SUCCESS)

        self.assertEqual(state.items, ItemInventory(shield=4, leap=2, super_dash=0))

    def test_leap_applies_every_crossed_recharge(self):
        state = EventState(
            position_m=130,
            items=ItemInventory(shield=0, leap=1, super_dash=0),
        )

        self.rules.apply(state, EventAction.LEAP, MoveOutcome.SUCCESS)

        self.assertEqual(state.position_m, 160)
        self.assertEqual(state.items.leap, 0)
        self.assertEqual(state.items.super_dash, 1)

    def test_crossing_300m_recharges_all_items(self):
        state = EventState(
            position_m=290,
            items=ItemInventory(shield=1, leap=0, super_dash=0),
        )

        self.rules.apply(state, EventAction.BASIC, MoveOutcome.SUCCESS)

        self.assertEqual(state.items, ItemInventory(shield=3, leap=1, super_dash=1))


class SummerEventConfigTest(unittest.TestCase):
    def test_config_converts_json_tile_keys_to_integers(self):
        payload = {
            "success_probabilities": {"0": 0.9, "10": 0.8},
            "reward_weights": {"100": 1, "200": 3, "300": 7, "350": 10},
            "reward_tiles": [100, 200, 300, 350],
            "finish_m": 400,
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "event.json"
            path.write_text(json.dumps(payload), encoding="utf-8")

            config = load_config(path)

        self.assertEqual(config.success_probabilities[10], 0.8)
        self.assertEqual(config.reward_weights[350], 10.0)

    def test_invalid_probability_is_rejected(self):
        config = SummerEventConfig(success_probabilities={0: 1.1})

        with self.assertRaises(ValueError):
            config.validate()

    def test_sparse_probability_file_accepts_only_known_tiles(self):
        payload = {
            "schema_version": 1,
            "event_id": "2026_summer_event",
            "tiles": {
                "20": {"success_probability": 0.75, "source": "provided"},
                "170": {"success_probability": 0.42, "note": "partial data"},
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "probability_data.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            dataset = load_probability_data(path)

        self.assertEqual(dataset.probabilities, {20: 0.75, 170: 0.42})
        self.assertEqual(dataset.missing_positions((0, 10, 20, 30)), (0, 10, 30))

    def test_probability_fingerprint_changes_when_data_changes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "probability_data.json"
            path.write_text(json.dumps({"tiles": {"20": 0.75}}), encoding="utf-8")
            first = load_probability_data(path)
            path.write_text(json.dumps({"tiles": {"20": 0.76}}), encoding="utf-8")
            second = load_probability_data(path)

        self.assertNotEqual(first.fingerprint, second.fingerprint)

    def test_missing_probability_is_interpolated_between_known_tiles(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "probability_data.json"
            path.write_text(
                json.dumps({"tiles": {"20": 0.8, "50": 0.5}}),
                encoding="utf-8",
            )
            dataset = load_probability_data(path)

        derived = derive_linear_probabilities(dataset, start_m=0, end_m=60)

        self.assertAlmostEqual(derived[30].success_probability, 0.7)
        self.assertAlmostEqual(derived[40].success_probability, 0.6)
        self.assertTrue(derived[30].derived)
        self.assertFalse(derived[20].derived)
        self.assertNotIn(10, derived)
        self.assertNotIn(60, derived)

    def test_event_bundle_resolves_probability_file_relative_to_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "probability_data.json").write_text(
                json.dumps({"tiles": {"40": {"success_probability": 0.6}}}),
                encoding="utf-8",
            )
            (root / "event_config.json").write_text(
                json.dumps({"probability_data_file": "probability_data.json"}),
                encoding="utf-8",
            )

            config, dataset = load_event_bundle(root / "event_config.json")

        self.assertEqual(config.success_probabilities, {40: 0.6})
        self.assertEqual(dataset.probabilities, {40: 0.6})

    def test_event_bundle_includes_bounded_inferred_probabilities(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "probability_data.json").write_text(
                json.dumps({"tiles": {"20": 0.8, "40": 0.6}}),
                encoding="utf-8",
            )
            (root / "event_config.json").write_text("{}", encoding="utf-8")

            config, dataset = load_event_bundle(root / "event_config.json")

        self.assertEqual(dataset.probabilities, {20: 0.8, 40: 0.6})
        self.assertAlmostEqual(config.success_probabilities[30], 0.7)
        self.assertNotIn(10, config.success_probabilities)

    def test_bundled_probability_data_matches_provided_tiles(self):
        config_path = Path(event_module.__file__).parent / "event_config.json"

        config, dataset = load_event_bundle(config_path)

        self.assertEqual(len(dataset.tiles), 24)
        self.assertEqual(dataset.probabilities[170], 0.50)
        self.assertEqual(dataset.probabilities[200], 0.50)
        self.assertEqual(dataset.tiles[170].source, "confirmed_ocr")
        self.assertEqual(dataset.tiles[200].source, "confirmed_ocr")
        self.assertEqual(dataset.probabilities[0], 1.0)
        self.assertEqual(dataset.probabilities[100], 0.75)
        self.assertEqual(dataset.probabilities[190], 0.45)
        self.assertEqual(dataset.probabilities[290], 0.41)
        self.assertAlmostEqual(config.success_probabilities[130], 0.565)
        self.assertNotIn(300, config.success_probabilities)

    def test_config_loads_item_recharge_rules(self):
        config_path = Path(event_module.__file__).parent / "event_config.json"

        config = load_config(config_path)

        self.assertEqual(config.item_recharges[100], {"shield": 2, "leap": 1})
        self.assertEqual(config.item_recharges[150], {"super_dash": 1})
        self.assertEqual(config.item_max_stacks, {"shield": 4, "leap": 2, "super_dash": 2})
        self.assertEqual(config.initial_item_stacks, {"shield": 2, "leap": 1, "super_dash": 2})
        self.assertTrue(config.reset_items_after_failure)
        self.assertEqual(config.verification_attempts, 3)
        self.assertEqual(config.outcome_check_attempts, 30)
        self.assertEqual(config.outcome_poll_interval_seconds, 0.2)
        self.assertEqual(config.ends_at, "2026-08-27T12:00:00+09:00")
        self.assertEqual(config.timezone, "Asia/Seoul")
        self.assertEqual(config.screen_layout_file, "screen_layout.json")

    def test_screen_layout_loads_reference_regions_and_taps(self):
        layout_path = Path(event_module.__file__).parent / "screen_layout.json"

        layout = load_screen_layout(layout_path)

        self.assertEqual(layout.reference_size, (1280, 720))
        self.assertEqual(layout.regions["current_node"], (580, 205, 120, 80))
        self.assertEqual(layout.regions["shield_button"], (845, 585, 120, 125))
        self.assertEqual(layout.regions["leap_button"], (985, 585, 120, 125))
        self.assertEqual(layout.regions["super_dash_button"], (1125, 585, 120, 125))
        self.assertEqual(layout.tap_points["shield"], (905, 640))
        self.assertEqual(layout.tap_points["leap"], (1047, 640))
        self.assertEqual(layout.tap_points["super_dash"], (1187, 640))

    def test_event_end_time_uses_absolute_korean_timestamp(self):
        config_path = Path(event_module.__file__).parent / "event_config.json"
        config = load_config(config_path)

        self.assertFalse(config.has_ended(datetime(2026, 8, 27, 2, 59, tzinfo=timezone.utc)))
        self.assertTrue(config.has_ended(datetime(2026, 8, 27, 3, 0, tzinfo=timezone.utc)))

    def test_screen_layout_scales_to_device_resolution(self):
        layout_path = Path(event_module.__file__).parent / "screen_layout.json"
        layout = load_screen_layout(layout_path)

        self.assertEqual(layout.scale_point("basic", (1920, 1080)), (960, 983))
        self.assertEqual(layout.scale_box("current_node", (1920, 1080)), (870, 308, 180, 120))

    def test_generated_policy_is_stale_when_probability_data_changes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            probability_path = root / "probability_data.json"
            probability_path.write_text(json.dumps({"tiles": {"0": 0.9}}), encoding="utf-8")
            dataset = load_probability_data(probability_path)
            policy_path = root / "generated_policy.json"
            policy_path.write_text(
                json.dumps({"source_probability_fingerprint": "old", "plans": {}}),
                encoding="utf-8",
            )

            generated_policy = load_generated_policy(policy_path)

        self.assertTrue(generated_policy.is_stale_for(dataset))


class SummerEventPolicyTest(unittest.TestCase):
    def test_policy_requires_probability_for_current_tile(self):
        rules = SummerEventRules()
        policy = SummerEventPolicy(SummerEventConfig(), rules)

        with self.assertRaises(MissingProbabilityData):
            policy.choose_action(EventState(items=ItemInventory(super_dash=0)))

    def test_policy_stops_at_configured_finish(self):
        rules = SummerEventRules()
        policy = SummerEventPolicy(SummerEventConfig(), rules)

        action = policy.choose_action(EventState(position_m=500, plan=EventPlan.TARGET_300M))

        self.assertIs(action, EventAction.STOP)

    def test_policy_can_select_guaranteed_dash_to_cross_target(self):
        config = SummerEventConfig(success_probabilities={90: 0.2, 80: 0.2})
        rules = SummerEventRules()
        policy = SummerEventPolicy(config, rules)
        state = EventState(
            position_m=90,
            plan=EventPlan.TARGET_100M,
            items=ItemInventory(shield=0, leap=1, super_dash=1),
        )

        action = policy.choose_action(state)

        self.assertIs(action, EventAction.SUPER_DASH)


class SummerEventPlannerTest(unittest.TestCase):
    def test_adaptive_model_predicts_unknown_tiles_and_learns_from_results(self):
        probabilities = {position: 0.8 - position / 1000 for position in range(0, 300, 10)}
        model = AdaptiveProbabilityModel(probabilities, observed_tiles={0, 10, 20}, end_m=490)
        prior = probabilities[300]

        changed = model.observe(300, EventAction.BASIC, MoveOutcome.SUCCESS)

        self.assertTrue(changed)
        self.assertIn(490, probabilities)
        self.assertGreater(probabilities[300], prior)
        self.assertEqual(model.observation_count(300), 1)
        known_prior = probabilities[10]
        self.assertTrue(model.observe(10, EventAction.BASIC, MoveOutcome.FAILURE))
        self.assertLess(probabilities[10], known_prior)
        self.assertFalse(model.observe(10, EventAction.SUPER_DASH, MoveOutcome.SUCCESS))

    def test_ocr_probability_replaces_prediction_for_missing_tile(self):
        probabilities = {position: 0.8 for position in range(0, 300, 10)}
        model = AdaptiveProbabilityModel(probabilities, observed_tiles={0, 10, 20}, end_m=490)

        changed = model.set_displayed_probability(300, 0.37)

        self.assertTrue(changed)
        self.assertEqual(probabilities[300], 0.37)
        self.assertFalse(model.set_displayed_probability(10, 0.25))
        self.assertEqual(probabilities[10], 0.8)

    def test_historical_outcomes_are_applied_once_before_planning(self):
        probabilities = {position: 0.8 for position in range(0, 300, 10)}
        model = AdaptiveProbabilityModel(probabilities, observed_tiles={0, 10, 20}, end_m=490)

        applied = model.apply_historical_outcomes({0: (3, 4), 330: (1, 2)})

        self.assertEqual(applied, 6)
        self.assertEqual(model.total_observations, 6)
        self.assertEqual(model.observation_count(0), 4)
        self.assertLess(probabilities[0], 0.8)

    def test_500m_high_score_policy_stops_after_first_arrival(self):
        config_path = Path(event_module.__file__).parent / "event_config.json"
        config, dataset = load_event_bundle(config_path)
        adaptive = AdaptiveProbabilityModel(
            config.success_probabilities,
            observed_tiles=dataset.tiles,
            end_m=490,
        )
        policy = PlannedSummerEventPolicy(
            config,
            SummerEventPlanner(config),
            adaptive_model=adaptive,
        )

        action = policy.choose_action(EventState(plan=EventPlan.TARGET_500M))

        self.assertIn(action, {EventAction.BASIC, EventAction.SHIELD, EventAction.LEAP, EventAction.SUPER_DASH})
        self.assertIs(
            policy.choose_action(EventState(position_m=500, plan=EventPlan.TARGET_500M)),
            EventAction.STOP,
        )

    def test_standard_plan_does_not_replan_after_runtime_result(self):
        config_path = Path(event_module.__file__).parent / "event_config.json"
        config, dataset = load_event_bundle(config_path)
        adaptive = AdaptiveProbabilityModel(
            config.success_probabilities,
            observed_tiles=dataset.tiles,
            end_m=490,
        )
        policy = PlannedSummerEventPolicy(
            config,
            SummerEventPlanner(config),
            adaptive_model=adaptive,
        )
        state = EventState(plan=EventPlan.TARGET_100M)
        policy.choose_action(state)
        self.assertTrue(policy._cache)
        cached_plans = dict(policy._cache)

        policy.observe_outcome(0, 0, EventAction.BASIC, MoveOutcome.FAILURE)
        policy.choose_action(state)

        self.assertEqual(policy._cache, cached_plans)
        self.assertTrue(all(policy._cache[key] is value for key, value in cached_plans.items()))
        self.assertEqual(adaptive.observation_count(0), 0)

    def test_runtime_observations_do_not_change_prepared_probability_model(self):
        config_path = Path(event_module.__file__).parent / "event_config.json"
        config, dataset = load_event_bundle(config_path)
        adaptive = AdaptiveProbabilityModel(
            config.success_probabilities,
            observed_tiles=dataset.tiles,
            end_m=490,
        )
        policy = PlannedSummerEventPolicy(
            config,
            SummerEventPlanner(config),
            adaptive_model=adaptive,
        )
        before = adaptive.probabilities[330]

        self.assertFalse(policy.observe_displayed_probability(330, 0.57))
        policy.observe_outcome(330, 330, EventAction.BASIC, MoveOutcome.SUCCESS)

        self.assertEqual(adaptive.probabilities[330], before)
        self.assertEqual(adaptive.observation_count(330), 0)

    def test_planner_builds_reproducible_target_plans(self):
        config_path = Path(event_module.__file__).parent / "event_config.json"
        config, _ = load_event_bundle(config_path)
        planner = SummerEventPlanner(config)

        plan = planner.build_plan(EventPlan.TARGET_100M)
        first = planner.simulate(plan, trials=2_000, seed=17)
        second = planner.simulate(plan, trials=2_000, seed=17)

        self.assertGreater(plan.success_probability, 0.0)
        self.assertGreater(plan.expected_drinks, 0.0)
        self.assertEqual(first, second)

    def test_exact_plan_and_monte_carlo_are_close(self):
        config_path = Path(event_module.__file__).parent / "event_config.json"
        config, _ = load_event_bundle(config_path)
        planner = SummerEventPlanner(config)
        plan = planner.build_plan(EventPlan.TARGET_200M)

        result = planner.simulate(plan, trials=20_000, seed=20260803)

        self.assertAlmostEqual(result.success_rate, plan.success_probability, delta=0.015)

    def test_runtime_policy_uses_exact_plan_for_observed_state(self):
        config_path = Path(event_module.__file__).parent / "event_config.json"
        config, _ = load_event_bundle(config_path)
        planner = SummerEventPlanner(config)
        policy = PlannedSummerEventPolicy(config, planner)

        action = policy.choose_action(EventState(plan=EventPlan.TARGET_100M))

        self.assertIs(action, EventAction.BASIC)

    def test_runtime_policy_advances_to_next_supported_target(self):
        config_path = Path(event_module.__file__).parent / "event_config.json"
        config, _ = load_event_bundle(config_path)
        policy = PlannedSummerEventPolicy(config, SummerEventPlanner(config))
        state = EventState(position_m=100, plan=EventPlan.TARGET_100M)

        action = policy.choose_action(state)

        self.assertIn(action, {EventAction.BASIC, EventAction.SHIELD, EventAction.LEAP, EventAction.SUPER_DASH})

    def test_runtime_policy_keeps_canonical_zero_route_after_midrun_start(self):
        config_path = Path(event_module.__file__).parent / "event_config.json"
        config, _ = load_event_bundle(config_path)
        planner = SummerEventPlanner(config)
        policy = PlannedSummerEventPolicy(config, planner)
        policy.prepare(
            EventState(
                position_m=50,
                plan=EventPlan.TARGET_200M,
                items=ItemInventory(shield=1, leap=0, super_dash=1),
            )
        )
        reset_state = EventState(position_m=0, plan=EventPlan.TARGET_200M)
        expected = SummerEventPlanner(config).build_plan(EventPlan.TARGET_200M).actions[
            (0, 2, 1, 2)
        ]

        with patch.object(policy_module.logger, "warning") as warning:
            action = policy.choose_action(reset_state)

        self.assertEqual(action, expected)
        warning.assert_not_called()

    def test_runtime_policy_precomputes_actual_200m_to_300m_transition_state(self):
        config_path = Path(event_module.__file__).parent / "event_config.json"
        config, _ = load_event_bundle(config_path)
        policy = PlannedSummerEventPolicy(config, SummerEventPlanner(config))
        policy.prepare(
            EventState(
                position_m=170,
                plan=EventPlan.TARGET_200M,
                items=ItemInventory(shield=1, leap=0, super_dash=1),
            )
        )
        transitioned = EventState(
            position_m=210,
            plan=EventPlan.TARGET_200M,
            items=ItemInventory(shield=0, leap=0, super_dash=0),
        )

        with patch.object(policy_module.logger, "warning") as warning:
            action = policy.choose_action(transitioned)

        self.assertIn((210, 0, 0, 0), policy._cache[EventPlan.TARGET_300M].actions)
        self.assertIs(action, policy._cache[EventPlan.TARGET_300M].actions[(210, 0, 0, 0)])
        warning.assert_not_called()

    def test_runtime_policy_continues_after_selected_target_with_remaining_items(self):
        config_path = Path(event_module.__file__).parent / "event_config.json"
        config, _ = load_event_bundle(config_path)
        policy = PlannedSummerEventPolicy(config, SummerEventPlanner(config))

        self.assertIs(
            policy.choose_action(
                EventState(
                    position_m=300,
                    plan=EventPlan.TARGET_300M,
                    items=ItemInventory(shield=2, leap=1, super_dash=1),
                )
            ),
            EventAction.SUPER_DASH,
        )
        self.assertIs(
            policy.choose_action(
                EventState(position_m=350, items=ItemInventory(shield=2, leap=1, super_dash=0))
            ),
            EventAction.SHIELD,
        )
        self.assertIs(
            policy.choose_action(
                EventState(position_m=400, items=ItemInventory(shield=0, leap=0, super_dash=0))
            ),
            EventAction.BASIC,
        )


class RecordingTapDevice:
    def __init__(self, results=None):
        self.results = list(results or [])
        self.taps = []

    def tap(self, x, y, delay=0.5):
        self.taps.append((x, y, delay))
        return self.results.pop(0) if self.results else True


class SequenceSkillVerifier:
    def __init__(self, results):
        self.results = list(results)
        self.actions = []

    def is_skill_selected(self, action):
        self.actions.append(action)
        return self.results.pop(0)


class SummerEventExecutorTest(unittest.TestCase):
    def setUp(self):
        layout_path = Path(event_module.__file__).parent / "screen_layout.json"
        self.layout = load_screen_layout(layout_path)

    def test_basic_action_taps_run_once(self):
        adb = RecordingTapDevice()
        executor = SummerEventExecutor(adb, self.layout)

        executor.execute(EventAction.BASIC)

        self.assertEqual(adb.taps, [(640, 655, 0.5)])

    def test_every_skill_requires_cancel_state_before_tapping_run(self):
        expected_points = {
            EventAction.SHIELD: (905, 640),
            EventAction.LEAP: (1047, 640),
            EventAction.SUPER_DASH: (1187, 640),
        }
        for action, point in expected_points.items():
            with self.subTest(action=action):
                adb = RecordingTapDevice()
                verifier = SequenceSkillVerifier([True])
                executor = SummerEventExecutor(
                    adb,
                    self.layout,
                    selection_verifier=verifier,
                )

                executor.execute(action)

                self.assertEqual(
                    adb.taps,
                    [(point[0], point[1], 0.25), (640, 655, 0.5)],
                )
                self.assertEqual(verifier.actions, [action])

    def test_skill_selection_retries_until_cancel_state_is_visible(self):
        adb = RecordingTapDevice()
        verifier = SequenceSkillVerifier([False, True])
        executor = SummerEventExecutor(
            adb,
            self.layout,
            selection_verifier=verifier,
        )

        executor.execute(EventAction.LEAP)

        self.assertEqual(
            adb.taps,
            [(1047, 640, 0.25), (1047, 640, 0.25), (640, 655, 0.5)],
        )

    def test_skill_selection_failure_never_taps_run(self):
        adb = RecordingTapDevice()
        verifier = SequenceSkillVerifier([False, False, False])
        executor = SummerEventExecutor(
            adb,
            self.layout,
            selection_verifier=verifier,
        )

        with self.assertRaisesRegex(EventInputError, "Cancel 상태"):
            executor.execute(EventAction.SUPER_DASH)

        self.assertEqual(adb.taps, [(1187, 640, 0.25)] * 3)


class UnknownTileProbabilityRecorderTest(unittest.TestCase):
    def test_records_only_missing_tiles_with_cumulative_probability(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            recorder = UnknownTileProbabilityRecorder(
                Path(temp_dir) / "logs" / "events",
                known_tiles={0, 10, 20},
                session="세션 1",
            )

            self.assertFalse(
                recorder.record(10, 10, EventAction.BASIC, MoveOutcome.SUCCESS)
            )
            self.assertFalse(
                recorder.record(300, 300, EventAction.SUPER_DASH, MoveOutcome.SUCCESS)
            )
            self.assertTrue(
                recorder.record(130, 130, EventAction.BASIC, MoveOutcome.SUCCESS)
            )
            self.assertTrue(
                recorder.record(130, 130, EventAction.BASIC, MoveOutcome.FAILURE)
            )

            log_path = (
                Path(temp_dir)
                / "logs"
                / "events"
                / "2026_summer_event_unknown_probabilities.csv"
            )
            rows = log_path.read_text(encoding="utf-8-sig").splitlines()

        self.assertEqual(len(rows), 3)
        self.assertIn("probability_tile_m", rows[0])
        self.assertIn("130,basic,failure,2,1,1,0.500000", rows[2])

    def test_records_ocr_probability_in_separate_event_log(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            recorder = UnknownTileProbabilityRecorder(
                Path(temp_dir) / "logs" / "events",
                known_tiles={0, 10},
                session="세션 1",
            )

            self.assertFalse(recorder.record_displayed_probability(330, 0.57))
            self.assertFalse(recorder.record_displayed_probability(330, 0.57))
            self.assertTrue(recorder.record_displayed_probability(330, 0.57))
            self.assertFalse(recorder.record_displayed_probability(330, 0.57))
            rows = recorder.ocr_log_path.read_text(encoding="utf-8-sig").splitlines()
            confirmed_rows = recorder.confirmed_log_path.read_text(
                encoding="utf-8-sig"
            ).splitlines()
            reloaded = UnknownTileProbabilityRecorder(
                Path(temp_dir) / "logs" / "events",
                known_tiles={0, 10},
                session="세션 2",
            )
            loaded = reloaded.load_displayed_probabilities()
            duplicate_recorded = reloaded.record_displayed_probability(330, 0.57)

        self.assertEqual(len(rows), 4)
        self.assertIn("330,0.570000", rows[1])
        self.assertIn("330,0.570000,3,high", confirmed_rows[1])
        self.assertEqual(loaded, {330: 0.57})
        self.assertFalse(duplicate_recorded)

    def test_ocr_confirmation_requires_three_consecutive_equal_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            recorder = UnknownTileProbabilityRecorder(
                Path(temp_dir) / "logs" / "events",
                known_tiles={0, 10},
            )

            self.assertFalse(recorder.record_displayed_probability(330, 0.57))
            self.assertFalse(recorder.record_displayed_probability(330, 0.58))
            self.assertFalse(recorder.record_displayed_probability(330, 0.58))
            self.assertIsNone(recorder.confirmed_probability(330))
            self.assertTrue(recorder.record_displayed_probability(330, 0.58))

            self.assertEqual(recorder.confirmed_probability(330), 0.58)

    def test_writes_applied_probability_table_by_position(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            recorder = UnknownTileProbabilityRecorder(
                Path(temp_dir) / "logs" / "events",
                known_tiles={0},
            )

            path = recorder.write_applied_probabilities(
                {0: 1.0, 330: 0.57},
                {0: "bundled", 330: "confirmed_ocr"},
            )
            rows = path.read_text(encoding="utf-8-sig").splitlines()

        self.assertEqual(len(rows), 3)
        self.assertIn("0,1.000000,bundled", rows[1])
        self.assertIn("330,0.570000,confirmed_ocr", rows[2])

    def test_promotes_three_matching_historical_ocr_rows_on_load(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            first = UnknownTileProbabilityRecorder(
                Path(temp_dir) / "logs" / "events",
                known_tiles={0},
            )
            self.assertFalse(first.record_displayed_probability(330, 0.57))
            self.assertFalse(first.record_displayed_probability(330, 0.57))
            # Simulate a legacy third raw row without a confirmed-data file.
            with first.ocr_log_path.open("a", encoding="utf-8") as stream:
                stream.write("2026-08-04T00:00:00+09:00,test,330,0.570000\n")

            reloaded = UnknownTileProbabilityRecorder(
                Path(temp_dir) / "logs" / "events",
                known_tiles={0},
            )

            self.assertEqual(reloaded.confirmed_probability(330), 0.57)
            self.assertFalse(reloaded.record_displayed_probability(330, 0.57))


class SummerEventBotSafetyTest(unittest.TestCase):
    def test_leap_result_is_recorded_without_runtime_policy_learning(self):
        class LeapPolicy:
            def __init__(self):
                self.observations = []

            def choose_action(self, state):
                return EventAction.LEAP

            def observe_outcome(self, position_m, observation_tile, action, outcome):
                self.observations.append((position_m, observation_tile, action, outcome))

        class SuccessObserver:
            def observe(self, state):
                return state

            def observe_outcome(self, action):
                return MoveOutcome.SUCCESS

        class RecordingProbabilityRecorder:
            def __init__(self):
                self.records = []

            def record(self, position_m, observation_tile, action, outcome):
                self.records.append((position_m, observation_tile, action, outcome))
                return True

        class NoopExecutor:
            def execute(self, action):
                pass

        policy = LeapPolicy()
        recorder = RecordingProbabilityRecorder()
        bot = event_module.SummerEventBot(
            state=EventState(position_m=100, items=ItemInventory(leap=1)),
            policy=policy,
            rules=SummerEventRules(),
            observer=SuccessObserver(),
            executor=NoopExecutor(),
            probability_recorder=recorder,
        )

        bot.step()

        expected = (100, 100, EventAction.LEAP, MoveOutcome.SUCCESS)
        self.assertEqual(policy.observations, [])
        self.assertEqual(recorder.records, [expected])
        self.assertEqual(bot.state.position_m, 130)

    def test_stop_request_during_outcome_does_not_invalidate_active_action(self):
        class StopDuringOutcomeObserver:
            def __init__(self):
                self.bot = None

            def observe(self, state):
                return state

            def observe_outcome(self, action):
                self.bot.set_user_action("stop")
                return MoveOutcome.SUCCESS

        class BasicPolicy:
            def choose_action(self, state):
                return EventAction.BASIC

        class NoopExecutor:
            def execute(self, action):
                pass

        observer = StopDuringOutcomeObserver()
        bot = event_module.SummerEventBot(
            state=EventState(),
            policy=BasicPolicy(),
            rules=SummerEventRules(),
            observer=observer,
            executor=NoopExecutor(),
        )
        observer.bot = bot

        stats = bot.run()

        self.assertFalse(bot.state.active)
        self.assertEqual(stats["attempts"], 1)
        self.assertEqual(stats["successes"], 1)
        self.assertEqual(stats["position_m"], 10)

    def test_stop_request_before_step_skips_input(self):
        class NoopObserver:
            def observe(self, state):
                return state

        class FailingPolicy:
            def choose_action(self, state):
                raise AssertionError("policy must not run after stop")

        bot = event_module.SummerEventBot(
            state=EventState(),
            policy=FailingPolicy(),
            rules=SummerEventRules(),
            observer=NoopObserver(),
            executor=None,
        )
        bot.set_user_action("stop")

        bot.step()

        self.assertFalse(bot.state.active)

    def test_logs_item_use_and_crossed_core_reward(self):
        class SuccessObserver:
            def observe(self, state):
                return state

            def observe_outcome(self, action):
                return MoveOutcome.SUCCESS

        class ShieldPolicy:
            def choose_action(self, state):
                return EventAction.SHIELD

        class NoopExecutor:
            def execute(self, action):
                pass

        bot = event_module.SummerEventBot(
            state=EventState(position_m=90, items=ItemInventory(shield=1, leap=0, super_dash=0)),
            policy=ShieldPolicy(),
            rules=SummerEventRules(),
            observer=SuccessObserver(),
            executor=NoopExecutor(),
        )

        with patch.object(bot_module.logger, "info") as info:
            bot.step()

        messages = [call.args[0] for call in info.call_args_list]
        self.assertTrue(any("이벤트 아이템 사용" in message for message in messages))
        self.assertTrue(any("핵심 보상 구간 통과" in message for message in messages))
        self.assertEqual(bot.get_stats()["plan_successes"], 1)
        self.assertEqual(bot.get_stats()["core_rewards_total"], 1)
        self.assertEqual(bot.get_stats()["rewards_100"], 1)

    def test_reused_outcome_waits_for_next_input_to_become_ready(self):
        class ReusingObserver:
            def observe(self, state):
                return state

            def observe_outcome(self, action):
                return MoveOutcome.SUCCESS

            def reuse_last_outcome_state(self, state):
                return True

        class BasicPolicy:
            def choose_action(self, state):
                return EventAction.BASIC

        class NoopExecutor:
            def execute(self, action):
                pass

        bot = event_module.SummerEventBot(
            state=EventState(),
            policy=BasicPolicy(),
            rules=SummerEventRules(),
            observer=ReusingObserver(),
            executor=NoopExecutor(),
        )

        with patch.object(bot_module.time, "sleep") as sleep:
            bot.step()

        sleep.assert_called_once_with(bot.REUSED_STATE_SETTLE_DELAY_SECONDS)
        self.assertTrue(bot._state_initialized)

    def test_crossing_reward_forces_fresh_scan_before_next_action(self):
        class RewardCrossingObserver:
            def __init__(self):
                self.reuse_calls = 0

            def observe(self, state):
                return state

            def observe_outcome(self, action):
                return MoveOutcome.SUCCESS

            def reuse_last_outcome_state(self, state):
                self.reuse_calls += 1
                return True

        class SuperDashPolicy:
            def choose_action(self, state):
                return EventAction.SUPER_DASH

        class NoopExecutor:
            def execute(self, action):
                pass

        observer = RewardCrossingObserver()
        bot = event_module.SummerEventBot(
            state=EventState(
                position_m=180,
                plan=EventPlan.TARGET_200M,
                items=ItemInventory(shield=0, leap=0, super_dash=1),
            ),
            policy=SuperDashPolicy(),
            rules=SummerEventRules(),
            observer=observer,
            executor=NoopExecutor(),
        )

        with patch.object(bot_module.time, "sleep") as sleep:
            bot.step()

        self.assertEqual(bot.state.position_m, 210)
        self.assertEqual(observer.reuse_calls, 0)
        self.assertFalse(bot._state_initialized)
        sleep.assert_not_called()

    def test_initial_scan_beyond_target_counts_plan_success_only_once(self):
        class ExistingProgressObserver:
            def observe(self, state):
                state.position_m = 210
                return state

        bot = event_module.SummerEventBot(
            state=EventState(plan=EventPlan.TARGET_200M),
            policy=None,
            rules=SummerEventRules(),
            observer=ExistingProgressObserver(),
            executor=None,
        )

        bot.initialize_state()
        bot.initialize_state()

        self.assertEqual(bot.get_stats()["plan_successes"], 1)

    def test_unprotected_failure_resets_run_and_keeps_automation_active(self):
        class FailureObserver:
            def observe(self, state):
                return state

            def observe_outcome(self, action):
                return MoveOutcome.FAILURE

        class BasicPolicy:
            def choose_action(self, state):
                return EventAction.BASIC

        class NoopExecutor:
            def execute(self, action):
                pass

        bot = event_module.SummerEventBot(
            state=EventState(position_m=320, items=ItemInventory(0, 0, 0)),
            policy=BasicPolicy(),
            rules=SummerEventRules(),
            observer=FailureObserver(),
            executor=NoopExecutor(),
        )

        bot.step()
        stats = bot.get_stats()

        self.assertTrue(bot.state.active)
        self.assertEqual(bot.state.position_m, 0)
        self.assertEqual(stats["attempts"], 1)
        self.assertEqual(stats["failures"], 1)
        self.assertEqual(stats["rollbacks"], 1)

    def test_super_dash_result_popup_stops_with_recognition_error_not_value_error(self):
        class FailureObserver:
            def observe(self, state):
                return state

            def observe_outcome(self, action):
                return MoveOutcome.FAILURE

        class SuperDashPolicy:
            def choose_action(self, state):
                return EventAction.SUPER_DASH

        class NoopExecutor:
            def execute(self, action):
                pass

        bot = event_module.SummerEventBot(
            state=EventState(items=ItemInventory(super_dash=1)),
            policy=SuperDashPolicy(),
            rules=SummerEventRules(),
            observer=FailureObserver(),
            executor=NoopExecutor(),
        )

        with self.assertRaisesRegex(EventRecognitionError, "슈퍼럭키 Cancel 상태"):
            bot.step()

        self.assertFalse(bot.state.active)

    def test_failure_allows_plan_success_to_be_counted_again_next_run(self):
        state = EventState(
            position_m=210,
            plan=EventPlan.TARGET_200M,
            plan_success_recorded=True,
        )
        state.stats.plan_successes = 1
        rules = SummerEventRules()

        rules.apply(state, EventAction.BASIC, MoveOutcome.FAILURE)

        self.assertFalse(state.plan_success_recorded)
        self.assertEqual(state.stats.plan_successes, 1)

    def test_first_action_uses_scanned_position_and_inventory(self):
        scanned_state = EventState(
            position_m=190,
            plan=EventPlan.TARGET_300M,
            items=ItemInventory(shield=1, leap=0, super_dash=2),
        )

        class InitialObserver:
            def __init__(self):
                self.observe_calls = 0

            def observe(self, previous_state):
                self.observe_calls += 1
                previous_state.position_m = scanned_state.position_m
                previous_state.items = ItemInventory(**vars(scanned_state.items))
                return previous_state

        class RecordingPolicy:
            def __init__(self):
                self.states = []

            def choose_action(self, state):
                self.states.append(
                    (state.position_m, state.items.shield, state.items.leap, state.items.super_dash)
                )
                return EventAction.STOP

        observer = InitialObserver()
        policy = RecordingPolicy()
        bot = event_module.SummerEventBot(
            state=EventState(plan=EventPlan.TARGET_300M),
            policy=policy,
            rules=SummerEventRules(),
            observer=observer,
            executor=None,
        )

        bot.run()

        self.assertEqual(observer.observe_calls, 1)
        self.assertEqual(policy.states, [(190, 1, 0, 2)])
        self.assertEqual(bot.get_stats()["position_m"], 190)

    def test_verification_failure_stops_after_configured_attempts(self):
        bot = event_module.SummerEventBot(
            state=EventState(),
            policy=None,
            rules=SummerEventRules(),
            observer=None,
            executor=None,
            verification_attempts=3,
        )
        calls = 0

        def fail_recognition():
            nonlocal calls
            calls += 1
            raise EventRecognitionError("unknown screen")

        with self.assertRaisesRegex(EventRecognitionError, "3회 실패"):
            bot._verify(fail_recognition, "테스트 화면")

        self.assertEqual(calls, 3)
        self.assertFalse(bot.state.active)

    def test_pending_outcome_is_polled_until_node_change_is_confirmed(self):
        outcomes = [EventOutcomePending("animating"), EventOutcomePending("animating"), MoveOutcome.SUCCESS]

        class PendingObserver:
            def observe_outcome(self, action):
                result = outcomes.pop(0)
                if isinstance(result, Exception):
                    raise result
                return result

        bot = event_module.SummerEventBot(
            state=EventState(),
            policy=None,
            rules=SummerEventRules(),
            observer=PendingObserver(),
            executor=None,
            outcome_check_attempts=5,
        )

        with patch.object(bot_module.time, "sleep") as sleep:
            self.assertIs(bot._observe_outcome(EventAction.SUPER_DASH), MoveOutcome.SUCCESS)

        self.assertEqual(sleep.call_count, 2)
        sleep.assert_called_with(0.2)
        self.assertEqual(outcomes, [])

    def test_outcome_timeout_reports_action_state_and_last_pending_reason(self):
        class PendingObserver:
            def observe_outcome(self, action):
                raise EventOutcomePending("현재 M 영역에 변화가 없음")

        bot = event_module.SummerEventBot(
            state=EventState(
                position_m=210,
                items=ItemInventory(shield=0, leap=0, super_dash=0),
            ),
            policy=None,
            rules=SummerEventRules(),
            observer=PendingObserver(),
            executor=None,
            outcome_check_attempts=1,
            outcome_poll_interval_seconds=0,
        )

        with patch.object(bot_module.time, "sleep"):
            with self.assertRaises(EventRecognitionError) as raised:
                bot._observe_outcome(EventAction.BASIC)

        message = str(raised.exception)
        self.assertIn("행동: 달리기", message)
        self.assertIn("기준 상태: 210M", message)
        self.assertIn("보호 0, 도움닫기 0, 슈퍼럭키 0", message)
        self.assertIn("마지막 대기: 현재 M 영역에 변화가 없음", message)

    def test_recognition_failure_batch_is_retried_before_stopping(self):
        calls = 0

        class TemporarilyUnknownObserver:
            def observe_outcome(self, action):
                nonlocal calls
                calls += 1
                if calls <= 3:
                    raise EventRecognitionError("reward popup animation")
                return MoveOutcome.SUCCESS

        bot = event_module.SummerEventBot(
            state=EventState(),
            policy=None,
            rules=SummerEventRules(),
            observer=TemporarilyUnknownObserver(),
            executor=None,
            verification_attempts=3,
            outcome_check_attempts=2,
        )

        with patch.object(bot_module.time, "sleep"):
            outcome = bot._observe_outcome(EventAction.BASIC)

        self.assertIs(outcome, MoveOutcome.SUCCESS)
        self.assertEqual(calls, 4)
        self.assertTrue(bot.state.active)

    def test_persistent_recognition_failure_stops_after_all_polling_batches(self):
        calls = 0

        class UnknownObserver:
            def observe_outcome(self, action):
                nonlocal calls
                calls += 1
                raise EventRecognitionError("unknown reward popup")

        bot = event_module.SummerEventBot(
            state=EventState(),
            policy=None,
            rules=SummerEventRules(),
            observer=UnknownObserver(),
            executor=None,
            verification_attempts=3,
            outcome_check_attempts=2,
        )

        with patch.object(bot_module.time, "sleep"):
            with self.assertRaisesRegex(EventRecognitionError, "2회 확인하지 못해"):
                bot._observe_outcome(EventAction.BASIC)

        self.assertEqual(calls, 6)
        self.assertFalse(bot.state.active)


class SummerEventObserverTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        event_root = Path(event_module.__file__).parent
        cls.fixture_root = Path(__file__).parents[1] / "fixtures" / "2026_summer_event"
        cls.observer = SummerEventObserver(
            adb=RecordingTapDevice(),
            layout=load_screen_layout(event_root / "screen_layout.json"),
            screenshot_path=Path("unused.png"),
            template_dir=Path("images") / "2026_summer_event",
        )

    @staticmethod
    def _read(path):
        return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)

    def test_recognizes_normal_screen_position_and_skill_stacks(self):
        zero = self.observer.analyze_frame(self._read(self.fixture_root / "normal_0m.png"))
        one_ninety = self.observer.analyze_frame(self._read(self.fixture_root / "normal_190m.png"))

        self.assertEqual(zero.kind, EventScreenKind.NORMAL)
        self.assertEqual(zero.position_m, 0)
        self.assertEqual(zero.success_probability, 1.0)
        self.assertEqual(zero.items, ItemInventory(shield=2, leap=1, super_dash=2))
        self.assertEqual(one_ninety.position_m, 190)
        self.assertEqual(one_ninety.success_probability, 0.45)
        self.assertEqual(one_ninety.items, ItemInventory(shield=1, leap=0, super_dash=2))

    def test_recognizes_cancel_state_for_every_skill_from_real_screens(self):
        samples = {
            EventAction.SHIELD: Path(
                r"E:\OneDrive\SC\Fraps\Screenshot_2026.08.03_20.28.45.121.png"
            ),
            EventAction.LEAP: Path(
                r"E:\OneDrive\SC\Fraps\Screenshot_2026.08.03_20.28.28.454.png"
            ),
            EventAction.SUPER_DASH: Path(
                r"E:\OneDrive\SC\Fraps\Screenshot_2026.08.03_20.28.58.071.png"
            ),
        }
        if not all(path.exists() for path in samples.values()):
            self.skipTest("User-provided Cancel screenshots are not available")

        for action, path in samples.items():
            with self.subTest(action=action):
                frame = self._read(path)
                self.assertTrue(self.observer.analyze_skill_selection(frame, action))

                other_actions = set(samples) - {action}
                self.assertTrue(
                    all(
                        not self.observer.analyze_skill_selection(frame, other)
                        for other in other_actions
                    )
                )

    def test_cancel_ocr_requires_at_least_93_percent_confidence(self):
        event_root = Path(event_module.__file__).parent

        def result_with_confidence(confidence):
            return (
                [[[[0, 0], [10, 0], [10, 10], [0, 10]], "Cancel", confidence]],
                None,
            )

        observer = SummerEventObserver(
            adb=RecordingTapDevice(),
            layout=load_screen_layout(event_root / "screen_layout.json"),
            screenshot_path=Path("unused.png"),
            template_dir=Path("images") / "2026_summer_event",
            ocr_engine=lambda *_args, **_kwargs: result_with_confidence(0.929),
        )
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)

        self.assertFalse(observer.analyze_skill_selection(frame, EventAction.SHIELD))
        observer.ocr_engine = lambda *_args, **_kwargs: result_with_confidence(0.93)
        self.assertTrue(observer.analyze_skill_selection(frame, EventAction.SHIELD))

    def test_standard_plan_observer_limits_ocr_runtime_threads(self):
        event_root = Path(event_module.__file__).parent
        with patch.object(observer_module, "RapidOCR", return_value=object()) as rapid_ocr:
            SummerEventObserver(
                adb=RecordingTapDevice(),
                layout=load_screen_layout(event_root / "screen_layout.json"),
                screenshot_path=Path("unused.png"),
                template_dir=Path("images") / "2026_summer_event",
                optimize_screen_analysis=True,
            )

        rapid_ocr.assert_called_once_with(
            intra_op_num_threads=2,
            inter_op_num_threads=2,
        )

    def test_500m_observer_keeps_default_ocr_runtime_threads(self):
        event_root = Path(event_module.__file__).parent
        with patch.object(observer_module, "RapidOCR", return_value=object()) as rapid_ocr:
            SummerEventObserver(
                adb=RecordingTapDevice(),
                layout=load_screen_layout(event_root / "screen_layout.json"),
                screenshot_path=Path("unused.png"),
                template_dir=Path("images") / "2026_summer_event",
                optimize_screen_analysis=False,
            )

        rapid_ocr.assert_called_once_with()

    def test_confirmed_tile_skips_probability_ocr(self):
        event_root = Path(event_module.__file__).parent
        observer = SummerEventObserver(
            adb=RecordingTapDevice(),
            layout=load_screen_layout(event_root / "screen_layout.json"),
            screenshot_path=Path("unused.png"),
            template_dir=Path("images") / "2026_summer_event",
            confirmed_probabilities={190: 0.45},
        )

        with patch.object(
            observer,
            "_recognize_success_probability",
            side_effect=AssertionError("confirmed tiles must not run probability OCR"),
        ):
            screen = observer.analyze_frame(self._read(self.fixture_root / "normal_190m.png"))

        self.assertEqual(screen.position_m, 190)
        self.assertEqual(screen.success_probability, 0.45)

    def test_outcome_analysis_skips_probability_ocr(self):
        frame = self._read(self.fixture_root / "normal_190m.png")

        with patch.object(
            self.observer,
            "_recognize_success_probability",
            side_effect=AssertionError("outcome polling must not run probability OCR"),
        ):
            screen = self.observer.analyze_frame(frame, recognize_probability=False)

        self.assertEqual(screen.position_m, 190)
        self.assertIsNone(screen.success_probability)

    def test_optimized_outcome_skips_all_ocr_when_position_region_is_unchanged(self):
        event_root = Path(event_module.__file__).parent
        observer = SummerEventObserver(
            adb=RecordingTapDevice(),
            layout=load_screen_layout(event_root / "screen_layout.json"),
            screenshot_path=Path("unused.png"),
            template_dir=Path("images") / "2026_summer_event",
            optimize_screen_analysis=True,
        )
        frame = self._read(self.fixture_root / "normal_190m.png")
        initial = observer.analyze_frame(frame)

        with patch.object(
            observer,
            "_recognize_position",
            side_effect=AssertionError("unchanged position must not run OCR"),
        ):
            unchanged = observer.analyze_frame(
                frame.copy(),
                recognize_probability=False,
                skip_ocr_if_position_unchanged=True,
            )

        self.assertEqual(initial.position_m, 190)
        self.assertEqual(unchanged.kind, EventScreenKind.UNCHANGED)

    def test_position_change_is_not_hidden_by_crop_average(self):
        first = np.zeros((80, 120, 3), dtype=np.uint8)
        second = first.copy()
        # A digit stroke may affect only a handful of pixels. The previous
        # average threshold treated this as unchanged.
        second[40, 60] = (1, 1, 1)

        self.assertFalse(
            SummerEventObserver._images_are_effectively_equal(first, second)
        )

    def test_optimized_outcome_still_reads_a_changed_position(self):
        event_root = Path(event_module.__file__).parent
        observer = SummerEventObserver(
            adb=RecordingTapDevice(),
            layout=load_screen_layout(event_root / "screen_layout.json"),
            screenshot_path=Path("unused.png"),
            template_dir=Path("images") / "2026_summer_event",
            optimize_screen_analysis=True,
        )
        observer.analyze_frame(self._read(self.fixture_root / "normal_0m.png"))

        changed = observer.analyze_frame(
            self._read(self.fixture_root / "normal_190m.png"),
            recognize_probability=False,
            skip_ocr_if_position_unchanged=True,
        )

        self.assertEqual(changed.kind, EventScreenKind.NORMAL)
        self.assertEqual(changed.position_m, 190)

    def test_standard_plan_reuses_decisive_outcome_below_300m(self):
        event_root = Path(event_module.__file__).parent
        observer = SummerEventObserver(
            adb=RecordingTapDevice(),
            layout=load_screen_layout(event_root / "screen_layout.json"),
            screenshot_path=Path("unused.png"),
            template_dir=Path("images") / "2026_summer_event",
            optimize_screen_analysis=True,
        )
        observed_items = ItemInventory(shield=1, leap=1, super_dash=2)
        observer._last_outcome_screen = ObservedEventScreen(
            EventScreenKind.NORMAL,
            position_m=190,
            items=observed_items,
        )
        state = EventState(position_m=180, plan=EventPlan.TARGET_200M)

        reused = observer.reuse_last_outcome_state(state)

        self.assertTrue(reused)
        self.assertEqual(state.position_m, 190)
        self.assertEqual(state.items, observed_items)
        self.assertEqual(observer._before_action.position_m, 190)

    def test_standard_plan_does_not_reuse_outcome_at_or_after_300m(self):
        event_root = Path(event_module.__file__).parent
        observer = SummerEventObserver(
            adb=RecordingTapDevice(),
            layout=load_screen_layout(event_root / "screen_layout.json"),
            screenshot_path=Path("unused.png"),
            template_dir=Path("images") / "2026_summer_event",
            optimize_screen_analysis=True,
        )
        observer._last_outcome_screen = ObservedEventScreen(
            EventScreenKind.NORMAL,
            position_m=300,
            items=ItemInventory(),
        )

        self.assertFalse(observer.reuse_last_outcome_state(EventState(position_m=290)))

    def test_optimized_shield_failure_checks_stack_when_position_is_unchanged(self):
        event_root = Path(event_module.__file__).parent
        observer = SummerEventObserver(
            adb=RecordingTapDevice(),
            layout=load_screen_layout(event_root / "screen_layout.json"),
            screenshot_path=Path("unused.png"),
            template_dir=Path("images") / "2026_summer_event",
            optimize_screen_analysis=True,
        )
        observer._before_action = EventState(
            position_m=220,
            items=ItemInventory(shield=2, leap=1, super_dash=1),
        )
        observed = ObservedEventScreen(
            EventScreenKind.NORMAL,
            position_m=220,
            items=ItemInventory(shield=1, leap=1, super_dash=1),
        )

        with patch.object(
            observer,
            "capture_and_analyze",
            return_value=observed,
        ) as capture:
            outcome = observer.observe_outcome(EventAction.SHIELD)

        self.assertIs(outcome, MoveOutcome.FAILURE)
        capture.assert_called_once_with(
            recognize_probability=False,
            skip_ocr_if_position_unchanged=False,
        )

    def test_optimized_basic_outcome_keeps_unchanged_position_shortcut(self):
        event_root = Path(event_module.__file__).parent
        observer = SummerEventObserver(
            adb=RecordingTapDevice(),
            layout=load_screen_layout(event_root / "screen_layout.json"),
            screenshot_path=Path("unused.png"),
            template_dir=Path("images") / "2026_summer_event",
            optimize_screen_analysis=True,
        )

        with patch.object(
            observer,
            "capture_and_analyze",
            return_value=ObservedEventScreen(EventScreenKind.UNCHANGED),
        ) as capture:
            with self.assertRaises(EventOutcomePending):
                observer.observe_outcome(EventAction.BASIC)

        capture.assert_called_once_with(
            recognize_probability=False,
            skip_ocr_if_position_unchanged=True,
        )

    def test_recognizes_stylized_75_percent_from_real_screen(self):
        path = Path(r"E:\OneDrive\SC\Fraps\Screenshot_2026.08.03_22.45.35.771.png")
        if not path.exists():
            self.skipTest("User-provided screenshot is not available")

        screen = self.observer.analyze_frame(self._read(path))

        self.assertEqual(screen.position_m, 60)
        self.assertEqual(screen.success_probability, 0.75)

    def test_recognizes_general_and_core_reward_as_same_popup_flow(self):
        general = self.observer.analyze_frame(self._read(self.fixture_root / "reward_general.png"))
        core = self.observer.analyze_frame(self._read(self.fixture_root / "reward_core.png"))

        self.assertEqual(general.kind, EventScreenKind.REWARD_POPUP)
        self.assertEqual(core.kind, EventScreenKind.REWARD_POPUP)

    def test_recognizes_failure_result_popup(self):
        result = self.observer.analyze_frame(self._read(self.fixture_root / "result_failure.png"))

        self.assertEqual(result.kind, EventScreenKind.RESULT_POPUP)

    def test_optimized_popup_search_recognizes_fixtures_using_small_regions(self):
        event_root = Path(event_module.__file__).parent
        observer = SummerEventObserver(
            adb=RecordingTapDevice(),
            layout=load_screen_layout(event_root / "screen_layout.json"),
            screenshot_path=Path("unused.png"),
            template_dir=Path("images") / "2026_summer_event",
            optimize_screen_analysis=True,
        )

        with patch.object(cv2, "matchTemplate", wraps=cv2.matchTemplate) as match_template:
            reward = observer.analyze_frame(self._read(self.fixture_root / "reward_general.png"))
            result = observer.analyze_frame(self._read(self.fixture_root / "result_failure.png"))

        self.assertEqual(reward.kind, EventScreenKind.REWARD_POPUP)
        self.assertEqual(result.kind, EventScreenKind.RESULT_POPUP)
        self.assertTrue(match_template.call_args_list)
        self.assertTrue(
            all(call.args[0].shape[:2] != (720, 1280) for call in match_template.call_args_list)
        )

    def test_failure_result_is_confirmed_before_reporting_failure(self):
        adb = RecordingTapDevice()
        event_root = Path(event_module.__file__).parent
        observer = SummerEventObserver(
            adb=adb,
            layout=load_screen_layout(event_root / "screen_layout.json"),
            screenshot_path=Path("unused.png"),
            template_dir=Path("images") / "2026_summer_event",
        )
        observer.capture_and_analyze = lambda **_kwargs: ObservedEventScreen(EventScreenKind.RESULT_POPUP)

        outcome = observer.observe_outcome(EventAction.BASIC)

        self.assertIs(outcome, MoveOutcome.FAILURE)
        self.assertEqual(adb.taps, [(640, 575, 0.2)])

    def test_repeated_lower_position_recovers_missed_leap_failure(self):
        event_root = Path(event_module.__file__).parent
        observer = SummerEventObserver(
            adb=RecordingTapDevice(),
            layout=load_screen_layout(event_root / "screen_layout.json"),
            screenshot_path=Path("unused.png"),
            template_dir=Path("images") / "2026_summer_event",
        )
        observer._before_action = EventState(
            position_m=100,
            items=ItemInventory(shield=1, leap=1, super_dash=1),
        )
        observer.capture_and_analyze = lambda **_kwargs: ObservedEventScreen(
            EventScreenKind.NORMAL,
            position_m=60,
            items=ItemInventory(shield=1, leap=0, super_dash=1),
        )

        with self.assertRaises(EventOutcomePending):
            observer.observe_outcome(EventAction.LEAP)
        with self.assertRaises(EventOutcomePending):
            observer.observe_outcome(EventAction.LEAP)

        self.assertIs(observer.observe_outcome(EventAction.LEAP), MoveOutcome.FAILURE)


if __name__ == "__main__":
    unittest.main()
