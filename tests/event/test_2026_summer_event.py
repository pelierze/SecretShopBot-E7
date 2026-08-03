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
MissingProbabilityData = policy_module.MissingProbabilityData


class SummerEventRulesTest(unittest.TestCase):
    def setUp(self):
        self.rules = SummerEventRules()

    def test_registry_loads_numeric_event_package(self):
        module = load_event_module("2026_summer_event")

        self.assertEqual(module.EVENT_ID, "2026_summer_event")

    def test_basic_failure_rolls_back_and_preserves_rewards(self):
        state = EventState(position_m=190, collected_reward_tiles={100})

        self.rules.apply(state, EventAction.BASIC, MoveOutcome.FAILURE)

        self.assertEqual(state.position_m, 0)
        self.assertEqual(state.collected_reward_tiles, {100})
        self.assertEqual(state.stats.rollbacks, 1)
        self.assertEqual(state.stats.drinks_used, 1)

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
        self.assertEqual(state.items.leap, 0)
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


if __name__ == "__main__":
    unittest.main()
