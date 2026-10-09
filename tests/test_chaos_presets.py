import json
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import ttk
from unittest.mock import Mock, patch

from src.gui import SecretShopGUI, SessionView


class ChaosPresetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'user' / 'exploration-presets.json'
        self.patch = patch.object(SessionView, '_chaos_preset_path', return_value=self.path)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)

    def view(self, session_id='session_1', choices=None):
        view = object.__new__(SessionView)
        view.session_id = session_id
        view.chaos_hero_choices = choices or {'knight': ['shadow_rose', 'ras'], 'thief': ['savior_adin', 'jenua']}
        view.chaos_hero_combos = {}
        view.chaos_rank_priority_combos = {}
        for role, ids in view.chaos_hero_choices.items():
            combo = ttk.Combobox(self.root, values=ids, state='readonly')
            combo.current(0)
            view.chaos_hero_combos[role] = combo
            priority = ttk.Combobox(self.root, values=['1순위', '2순위', '3순위', '4순위', '제외'])
            priority.set('제외')
            view.chaos_rank_priority_combos[role] = priority
        view.chaos_cost_fallback = tk.BooleanVar(self.root, True)
        view._check_chaos_hero_cost_warning = Mock()
        view._update_macro_dependent_controls = Mock()
        return view

    def test_restart_and_reordered_catalog_restore_ids_priorities_and_fallback(self):
        view = self.view()
        view.chaos_hero_combos['knight'].current(1)
        view.chaos_rank_priority_combos['knight'].set('1순위')
        view.chaos_cost_fallback.set(False)
        view._save_chaos_preset()
        restored = self.view(choices={'knight': ['ras', 'shadow_rose'], 'thief': ['jenua', 'savior_adin']})
        restored._restore_chaos_preset()
        self.assertEqual(restored.chaos_hero_combos['knight'].get(), 'ras')
        self.assertEqual(restored.chaos_hero_combos['thief'].get(), 'savior_adin')
        self.assertEqual(restored.chaos_rank_priority_combos['knight'].get(), '1순위')
        self.assertFalse(restored.chaos_cost_fallback.get())

    def test_sessions_keep_independent_last_presets(self):
        first, second = self.view(), self.view('session_2')
        first.chaos_hero_combos['knight'].current(1)
        first._save_chaos_preset()
        second._save_chaos_preset()
        first._restore_chaos_preset()
        second._restore_chaos_preset()
        self.assertEqual(first.chaos_hero_combos['knight'].get(), 'ras')
        self.assertEqual(second.chaos_hero_combos['knight'].get(), 'shadow_rose')

    def test_update_snapshot_does_not_override_persistent_preset(self):
        view = self.view()
        app = object.__new__(SecretShopGUI)
        app.sessions = [view]
        old_values = [{key: var.get() for key, var in app._update_variables(view)}]
        view.chaos_hero_combos['knight'].current(1)
        view._save_chaos_preset()
        app._apply_update_settings(old_values)
        self.assertEqual(view.chaos_hero_combos['knight'].get(), 'ras')
        self.assertEqual(json.loads(self.path.read_text(encoding='utf-8'))['sessions']['session_1']['heroes']['knight'], 'ras')

    def test_removed_hero_and_invalid_priority_keep_defaults(self):
        view = self.view()
        view._save_chaos_preset()
        data = json.loads(self.path.read_text(encoding='utf-8'))
        data['sessions']['session_1']['heroes']['knight'] = 'removed_hero'
        data['sessions']['session_1']['rank_priorities']['knight'] = 'invalid'
        self.path.write_text(json.dumps(data), encoding='utf-8')
        view._restore_chaos_preset()
        self.assertEqual(view.chaos_hero_combos['knight'].get(), 'shadow_rose')
        self.assertEqual(view.chaos_rank_priority_combos['knight'].get(), '제외')

    def test_failed_atomic_save_preserves_previous_preset(self):
        view = self.view()
        view._save_chaos_preset()
        before = self.path.read_bytes()
        view.chaos_hero_combos['knight'].current(1)
        with patch('src.gui.os.replace', side_effect=OSError('disk full')), self.assertLogs('src.gui', level='ERROR'):
            view._save_chaos_preset()
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.path.parent.glob('*.tmp')), [])

    def test_gui_selection_is_saved_and_restored_without_starting_bot(self):
        with patch.object(SecretShopGUI, '_setup_logging'), patch.object(SecretShopGUI, '_start_settings_update'), patch.object(SecretShopGUI, '_start_release_check'):
            app = SecretShopGUI(self.root)
        session = app.sessions[0]
        combo = session.chaos_hero_combos['knight']
        combo.current(session.chaos_hero_choices['knight'].index('ras'))
        combo.event_generate('<<ComboboxSelected>>')
        self.root.update()
        self.assertEqual(json.loads(self.path.read_text(encoding='utf-8'))['sessions']['session_1']['heroes']['knight'], 'ras')
        combo.current(0)
        session._restore_chaos_preset()
        self.assertEqual(combo.current(), session.chaos_hero_choices['knight'].index('ras'))

    def test_storage_follows_windows_user_not_install_directory(self):
        self.patch.stop()
        with patch.dict('os.environ', {'LOCALAPPDATA': str(Path(self.temp.name) / 'another-user')}):
            self.assertEqual(SessionView._chaos_preset_path(), Path(self.temp.name) / 'another-user/SecretShopBot-E7/exploration-presets.json')


if __name__ == '__main__':
    unittest.main()
