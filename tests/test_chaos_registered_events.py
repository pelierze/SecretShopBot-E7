import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.chaos.exploration import NodeProgressionBot
from src.chaos.node_observer import NodeObserver
from src.image_matcher import read_image

ROOT = Path(__file__).resolve().parents[1]


class RegisteredEventTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.observer = NodeObserver(ROOT)

    def test_every_registered_event_uses_saved_rules_in_random_mode(self):
        for event in self.observer.config['events']:
            with self.subTest(event=event['id']), tempfile.TemporaryDirectory() as tmp:
                source = self.observer.config['markers'][event['state_marker']]['file']
                frame = read_image(str(ROOT/source))
                bot = NodeProgressionBot(Mock(), ROOT, tmp, self.observer, event_mode='random')
                bot.event_context = True
                bot._capture = Mock(return_value=frame)
                bot._wait = lambda phase, predicate: predicate(frame)
                bot._tap = Mock()
                bot._event_transition = Mock(return_value='map')
                with patch('src.chaos.exploration.random.choice') as random_choice:
                    bot._unknown_event()
                    random_choice.assert_not_called()
                bot._tap.assert_called_once()
                self.assertIn(list(bot._tap.call_args.args[0]), [c['bounds'] for c in event['choices']])

    def test_new_events_choose_reviewed_safe_outcome(self):
        expected = {'blood_shelter':78, 'open_spellbook':838, 'broken_stele':268,
                    'bent_bars':838, 'sharp_teeth':648, 'wind_prayer':648,
                    'feuding_tablet':648, 'torn_map':648, 'wandering_ghost':268,
                    'rusted_bars':458}
        for name, x in expected.items():
            with self.subTest(event=name):
                frame = read_image(str(ROOT/f'images/chaos/node_progression/raw/event_{name}_live.png'))
                self.assertEqual(self.observer.known_event(frame), name)
                self.assertEqual(self.observer.event_choice(frame), (x,556,362,131))

    def test_rusted_bars_does_not_choose_when_reviewed_choice_changes(self):
        frame = read_image(str(ROOT/'images/chaos/node_progression/raw/event_rusted_bars_live.png'))
        frame[587:677,476:802] = 0
        self.assertEqual(self.observer.known_event(frame), 'rusted_bars')
        self.assertIsNone(self.observer.event_choice(frame))

    def test_rusted_bars_does_not_fall_back_to_unreviewed_choices(self):
        frame = read_image(str(ROOT/'images/chaos/node_progression/raw/event_rusted_bars_live.png'))
        self.assertIsNone(self.observer.event_choice(frame, excluded=[(458,556,362,131)]))

    def test_late_registration_discards_random_candidate(self):
        cards = [(268,556,362,131), (648,556,362,131)]
        for recognition_capture in (2, 3):
            with self.subTest(capture=recognition_capture), tempfile.TemporaryDirectory() as tmp:
                bot = NodeProgressionBot(Mock(), ROOT, tmp, self.observer, event_mode='random')
                bot.observer = Mock()
                counter = [0]
                def capture():
                    counter[0] += 1
                    return counter[0]
                bot._capture = capture
                bot._wait = lambda phase, predicate: predicate(capture())
                bot._classify = lambda s: 'event' if s >= recognition_capture else 'unknown_event'
                bot._event_signature = Mock(return_value='same-page')
                bot.observer.known_event_candidates.side_effect = lambda s: ['saved'] if s >= recognition_capture else []
                bot.observer.event_cards.return_value = cards
                bot.observer.available_event_cards.return_value = cards
                bot._start_report = Mock()
                bot._event = Mock(return_value='saved_rule')
                bot._tap = Mock()
                self.assertEqual(bot._unknown_event(), 'saved_rule')
                bot._event.assert_called_once()
                bot._tap.assert_not_called()
