import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from src.failure_report import save_failure_report
from src.gui import SessionView


class FailureReportTests(unittest.TestCase):
    def test_report_contains_recent_logs_and_original_frame_in_unicode_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / '한글 경로' / 'logs'
            root.mkdir(parents=True)
            log_file = root / 'bot.log'
            log_file.write_text('오래된 기록\n' * 20000 + '인식 시간 초과\n', encoding='utf-8')
            frame = np.full((20, 30, 3), 77, dtype=np.uint8)
            bot = SimpleNamespace(active=SimpleNamespace(last_screen=frame))
            controller = Mock()
            result = dict(status='failed', phase='보상 확인', reason='시간 초과')
            with self.assertLogs('src.failure_report', level='WARNING') as logs:
                report = save_failure_report(root, log_file, result, bot, '세션/1', 'chaos', controller)
            self.assertEqual(report.parent, root / 'report')
            metadata = json.loads((report / 'report.json').read_text(encoding='utf-8'))
            self.assertEqual(metadata['result'], result)
            self.assertEqual(metadata['screenshot_source'], 'last_observed_frame')
            screenshot = cv2.imdecode(np.frombuffer((report / 'screen.png').read_bytes(), np.uint8), cv2.IMREAD_COLOR)
            np.testing.assert_array_equal(screenshot, frame)
            recent = (report / 'recent.log').read_text(encoding='utf-8')
            self.assertIn('인식 시간 초과', recent)
            self.assertLess(len(recent.splitlines()), 1010)
            self.assertTrue(any(str(report.resolve()) in line and '첨부' in line for line in logs.output))
            controller.screenshot.assert_not_called()

    def test_event_observer_cached_file_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'event.png'
            source.write_bytes(cv2.imencode('.png', np.zeros((4, 5, 3), np.uint8))[1].tobytes())
            log = root / 'bot.log'; log.write_text('실패', encoding='utf-8')
            bot = SimpleNamespace(observer=SimpleNamespace(screenshot_path=source))
            report = save_failure_report(root, log, {}, bot, 'event', 'event')
            self.assertEqual((report / 'screen.png').read_bytes(), source.read_bytes())

    def test_capture_failure_still_saves_log_and_reason(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / 'bot.log'; log.write_text('캡처 오류', encoding='utf-8')
            controller = Mock(screenshot=Mock(side_effect=RuntimeError('창 최소화')))
            report = save_failure_report(root, log, {'reason': '인식 실패'}, SimpleNamespace(), 's', 'chaos', controller)
            self.assertTrue((report / 'recent.log').is_file())
            metadata = json.loads((report / 'report.json').read_text(encoding='utf-8'))
            self.assertFalse(metadata['screenshot_saved'])
            self.assertIn('창 최소화', metadata['screenshot_errors'])

    def test_report_write_failure_does_not_raise(self):
        with patch('src.failure_report.Path.mkdir', side_effect=OSError('disk full')):
            with self.assertLogs('src.failure_report', level='ERROR'):
                self.assertIsNone(save_failure_report('logs', 'bot.log', {}, None, 's', 'chaos'))


class FailureReportLifecycleTests(unittest.TestCase):
    def view(self, result, user_stop=False):
        view = object.__new__(SessionView)
        view.name = 'test'
        view.current_mode = 'chaos'
        view.runtime_dir = Path('logs') / 'test'
        view.adb_controller = Mock()
        view.was_stopped_by_user = user_stop
        view.root = Mock()
        view.app = SimpleNamespace(is_closing=False)
        view.bot = Mock(run=Mock(return_value=result))
        view.log = Mock()
        view.reroll_sound_var = Mock()
        return view

    @patch('src.gui.save_failure_report')
    def test_chaos_failure_return_or_exception_creates_report(self, save):
        result = dict(status='failed', reason='시간 초과')
        view = self.view(result)
        view._run_chaos_bot()
        self.assertEqual(save.call_args.args[2], result)
        save.reset_mock()
        view.bot.run.side_effect = RuntimeError('실행 오류')
        view._run_chaos_bot()
        self.assertEqual(save.call_args.args[2]['reason'], '실행 오류')

    @patch('src.gui.save_failure_report')
    def test_completion_and_user_stop_do_not_create_reports(self, save):
        for result, user_stop in [({'status': 'completed'}, False),
                                  ({'status': 'stopped', 'reason': '사용자 중지'}, True),
                                  ({'status': 'failed'}, True),
                                  ({'status': 'stopped', 'reason': '사용자 중지'}, False),
                                  ({'status': 'stopped', 'reason': '패배 결과 처리 후 중지'}, False)]:
            self.view(result, user_stop)._run_chaos_bot()
        save.assert_not_called()

    @patch('src.gui.save_failure_report')
    def test_unconfirmed_exploration_end_creates_report(self, save):
        self.view({'status': 'stopped', 'reason': '탐사 정산 복귀 완료 — 승패 확인 불가'})._run_chaos_bot()
        save.assert_called_once()

    @patch('src.gui.save_failure_report')
    def test_other_automation_exceptions_create_reports(self, save):
        for method, args in [('_run_bot', (1, 1)), ('_run_reroll_bot', ()),
                             ('_run_penguin_bot', ()), ('_run_event_bot', ())]:
            with self.subTest(method=method):
                save.reset_mock()
                view = self.view({})
                view.bot.run.side_effect = RuntimeError('장치 연결 실패')
                getattr(view, method)(*args)
                self.assertEqual(save.call_count, 1)
                self.assertEqual(save.call_args.args[2]['reason'], '장치 연결 실패')

    @patch('src.gui.save_failure_report')
    def test_report_exception_does_not_prevent_finishing_ui(self, save):
        save.side_effect = OSError('disk full')
        view = self.view({'status': 'failed'})
        view._run_chaos_bot()
        self.assertEqual(view.root.after.call_args.args[0], 0)

    @patch('src.gui.save_failure_report')
    def test_returned_failure_and_safety_stop_create_reports(self, save):
        for method, args, result in [('_run_bot', (1, 1), {'status': 'failed'}),
                                     ('_run_penguin_bot', (), {'status': 'failed'}),
                                     ('_run_reroll_bot', (), {'stop_reason': '인식 실패'})]:
            with self.subTest(method=method):
                save.reset_mock()
                view = self.view(result)
                for formatter in ('_format_stats_summary', '_format_penguin_summary', '_format_reroll_summary'):
                    setattr(view, formatter, Mock(return_value='중지'))
                getattr(view, method)(*args)
                save.assert_called_once()


if __name__ == '__main__':
    unittest.main()
