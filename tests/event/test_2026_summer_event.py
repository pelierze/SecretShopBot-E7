import importlib
import json
import tempfile
import unittest
from pathlib import Path

from src.event import (
    EventAction,
    EventPlan,
    EventState,
    ItemInventory,
    MoveOutcome,
    load_event_module,
)


event_module = importlib.import_module("src.event.events.2026_summer_event")
policy_module = importlib.import_module("src.event.events.2026_summer_event.policy")
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

        self.assertEqual(len(dataset.tiles), 22)
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
        self.assertEqual(config.screen_layout_file, "screen_layout.json")

    def test_screen_layout_loads_reference_regions_and_taps(self):
        layout_path = Path(event_module.__file__).parent / "screen_layout.json"

        layout = load_screen_layout(layout_path)

        self.assertEqual(layout.reference_size, (1280, 720))
        self.assertEqual(layout.regions["current_node"], (580, 205, 120, 80))
        self.assertEqual(layout.tap_points["shield"], (905, 640))
        self.assertEqual(layout.tap_points["leap"], (1047, 640))
        self.assertEqual(layout.tap_points["super_dash"], (1187, 640))

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

    def test_policy_stops_at_400m(self):
        rules = SummerEventRules()
        policy = SummerEventPolicy(SummerEventConfig(), rules)

        action = policy.choose_action(EventState(position_m=400, plan=EventPlan.TARGET_300M))

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


if __name__ == "__main__":
    unittest.main()
