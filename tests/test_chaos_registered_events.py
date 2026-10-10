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

    def test_every_registered_event_uses_available_buttons_in_random_mode(self):
        for event in self.observer.config['events']:
            with self.subTest(event=event['id']), tempfile.TemporaryDirectory() as tmp:
                source = self.observer.config['markers'][event['state_marker']]['file']
                frame = read_image(str(ROOT/source))
                bot = NodeProgressionBot(Mock(), ROOT, tmp, self.observer)
                bot.event_context = True
                bot._capture = Mock(return_value=frame)
                bot._wait = lambda phase, predicate: predicate(frame)
                bot._tap = Mock()
                bot._event_transition = Mock(return_value='map')
                with patch('src.chaos.exploration.random.choice', side_effect=lambda choices: choices[0]) as choose, patch.object(self.observer, 'event_choice', side_effect=AssertionError('text rules must not be used')):
                    self.assertEqual(bot._event(), 'map')
                    choose.assert_called_once()
                bot._tap.assert_called_once()
                self.assertIn(bot._tap.call_args.args[0], self.observer.available_event_cards(frame, self.observer.event_cards(frame)))

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

    def test_late_registration_keeps_verified_random_candidate(self):
        cards = [(268,556,362,131), (648,556,362,131)]
        with tempfile.TemporaryDirectory() as tmp:
            bot = NodeProgressionBot(Mock(), ROOT, tmp, self.observer)
            bot.observer = Mock()
            bot._capture = Mock(side_effect=[1,2,3])
            bot._wait = lambda phase, predicate: predicate(bot._capture())
            bot._classify = lambda screen: 'event' if screen >= 2 else 'unknown_event'
            bot._event_signature = Mock(return_value='same-page')
            bot.observer.event_cards.return_value = cards
            bot.observer.available_event_cards.return_value = cards
            bot._start_report = Mock()
            bot._report = Mock()
            bot._event_transition = Mock(return_value='map')
            bot._tap = Mock()
            with patch('src.chaos.exploration.random.choice', return_value=cards[1]):
                self.assertEqual(bot._unknown_event(), 'map')
            bot._tap.assert_called_once_with(cards[1])


    def test_latest_library_page_uses_buttons_without_text_matching(self):
        frame = read_image(str(ROOT / 'images/chaos/node_progression/raw/event_library_book_local_live.png'))
        self.assertIsNone(self.observer.event_choice(frame))
        cards = self.observer.event_cards(frame)
        self.assertEqual(cards, [(268,556,362,131), (648,556,362,131)])
        with tempfile.TemporaryDirectory() as tmp:
            bot = NodeProgressionBot(Mock(), ROOT, tmp, self.observer)
            bot.event_context = True
            bot._capture = Mock(return_value=frame)
            bot._wait = lambda phase, predicate: predicate(frame)
            bot._tap = Mock()
            bot._event_transition = Mock(return_value='map')
            with patch('src.chaos.exploration.random.choice', return_value=cards[1]), patch.object(self.observer, 'event_choice', side_effect=AssertionError('text rule called')):
                self.assertEqual(bot._event(), 'map')
            bot._tap.assert_called_once_with(cards[1])
