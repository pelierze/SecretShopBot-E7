import tkinter as tk
import unittest
import tempfile
from pathlib import Path
from src.log_split_view import LogSplitView
from types import SimpleNamespace
from unittest.mock import patch

from src.gui import SecretShopGUI


class SmallWindowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        runtime_patch = patch('src.gui.get_runtime_root', return_value=Path(self.temp.name))
        runtime_patch.start()
        self.addCleanup(runtime_patch.stop)
        self.root = tk.Tk()
        self.callback_errors = []
        self.root.report_callback_exception = lambda *error: self.callback_errors.append(error)
        self.addCleanup(self._close)
        with patch.object(SecretShopGUI, '_setup_logging'), patch.object(SecretShopGUI, '_start_settings_update'), patch.object(SecretShopGUI, '_start_release_check'):
            self.app = SecretShopGUI(self.root)
        self.root.geometry('800x600')
        self.root.update()
        self.session = self.app.sessions[0]

    def _close(self):
        self.root.destroy()
        self.assertFalse(self.callback_errors, self.callback_errors)

    def test_every_mode_and_log_can_be_reached_in_small_window(self):
        session = self.session
        self.assertEqual(
            [session.mode_notebook.tab(tab, 'text') for tab in session.mode_notebook.tabs()],
            ['비밀상점', '펭귄', '자동 탐사', '이벤트'],
        )
        for tab in (session.shop_tab, session.penguin_tab, session.chaos_tab, session.event_tab):
            with self.subTest(tab=tab):
                session.mode_notebook.select(tab)
                self.root.update()
                area = session.frame.options
                self.assertGreater(area.content.winfo_height(), area.canvas.winfo_height())
                area.canvas.yview_moveto(1)
                self.root.update()
                self.assertAlmostEqual(area.canvas.yview()[1], 1, places=2)
                bottom = session.log_text.winfo_rooty() + session.log_text.winfo_height()
                self.assertLessEqual(bottom, session.frame.winfo_rooty() + session.frame.winfo_height())
                self.assertGreaterEqual(session.log_frame.winfo_rooty(), area.winfo_rooty() + area.winfo_height())
                area.canvas.xview_moveto(1)
                self.assertAlmostEqual(area.canvas.xview()[1], 1, places=2)

    def test_wheel_routes_only_active_session_without_changing_combo(self):
        area = self.session.frame.options
        combo = self.session.chaos_hero_combos['knight']
        value = combo.get()
        other = self.app.sessions[1].frame.options.canvas.yview()
        area.canvas.yview_moveto(0)
        self.assertEqual(area._wheel(SimpleNamespace(widget=combo, delta=-120, state=0, num=None)), 'break')
        self.assertGreater(area.canvas.yview()[0], 0)
        self.assertEqual(combo.get(), value)
        self.assertEqual(self.app.sessions[1].frame.options.canvas.yview(), other)

    def test_connection_header_stays_fixed_while_functions_scroll(self):
        session = self.session
        area = session.frame.options
        self.assertIs(session.connection_frame.master, session.frame.header)
        self.assertNotIn(area._tag, session.scan_btn.bindtags())
        self.assertNotIn(area._tag, session.stove_resize_btn.bindtags())
        header_position = session.connection_frame.winfo_rooty()
        log_position = session.log_frame.winfo_rooty()
        area.canvas.yview_moveto(0)
        self.root.update()
        function_position = session.mode_notebook.winfo_rooty()
        session.start_btn.event_generate('<MouseWheel>', delta=-120)
        self.root.update()
        self.assertGreater(area.canvas.yview()[0], 0)
        self.assertLess(session.mode_notebook.winfo_rooty(), function_position)
        self.assertEqual(session.connection_frame.winfo_rooty(), header_position)
        self.assertEqual(session.log_frame.winfo_rooty(), log_position)
        self.assertLessEqual(session.connection_frame.winfo_rooty() + session.connection_frame.winfo_height(), area.winfo_rooty())

    def test_log_expansion_keeps_connection_header_visible(self):
        session = self.session
        height = session.connection_frame.winfo_height()
        session._toggle_log()
        self.root.update()
        self.assertTrue(session.connection_frame.winfo_ismapped())
        self.assertFalse(session.frame.options.winfo_ismapped())
        self.assertEqual(session.connection_frame.winfo_height(), height)
        self.assertGreaterEqual(session.log_frame.winfo_rooty(), session.connection_frame.winfo_rooty() + height)

    def test_log_wheel_and_keyboard_focus(self):
        area = self.session.frame.options
        text = self.session.log_text
        text.configure(state='normal')
        text.insert('end', '\n'.join(str(i) for i in range(150)))
        text.yview_moveto(.3)
        self.root.update()
        before = area.canvas.yview()
        self.assertNotIn(area._tag, text.bindtags())
        text.event_generate('<MouseWheel>', delta=-120)
        self.root.update()
        self.assertEqual(area.canvas.yview(), before)
        area.canvas.yview_moveto(0)
        self.session.mode_notebook.select(self.session.chaos_tab)
        self.root.update()
        area._focus(SimpleNamespace(widget=self.session.chaos_target_clears_entry))
        self.root.update()
        self.assertGreater(area.canvas.yview()[0], 0)
        self.assertGreaterEqual(self.session.chaos_target_clears_entry.winfo_rooty(), area.canvas.winfo_rooty())

    def test_selected_tab_height_releases_space_for_logs(self):
        session = self.session
        heights = []
        log_height = session.log_frame.winfo_height()
        for tab in (session.chaos_tab, session.penguin_tab):
            session.mode_notebook.select(tab)
            self.root.update()
            self.assertEqual(int(session.mode_notebook.cget('height')), tab.winfo_reqheight())
            heights.append(session.mode_notebook.winfo_height())
            self.assertEqual(session.log_frame.winfo_height(), log_height)
        self.assertGreater(max(heights), min(heights))

    def test_tab_switch_starts_at_top_and_notebook_focus_does_not_scroll_down(self):
        session = self.session
        area = session.frame.options
        area.canvas.yview_moveto(1)
        self.root.update()
        self.assertGreater(area.canvas.yview()[0], 0)
        session.mode_notebook.select(session.chaos_tab)
        self.root.update()
        self.assertEqual(area.canvas.yview()[0], 0)
        session.mode_notebook.focus_force()
        self.root.update()
        self.assertEqual(area.canvas.yview()[0], 0)
        area.canvas.yview_moveto(.4)
        self.root.update()
        position = area.canvas.yview()[0]
        session._resize_mode_tab()
        self.root.update()
        self.assertAlmostEqual(area.canvas.yview()[0], position, places=2)

    def test_focus_on_tall_tab_container_keeps_tab_strip_visible(self):
        session = self.session
        area = session.frame.options
        for tab in (session.shop_tab, session.chaos_tab):
            with self.subTest(tab=tab):
                session.mode_notebook.select(tab)
                self.root.update()
                area.canvas.yview_moveto(0)
                tab.focus_force()
                self.root.update()
                self.assertEqual(area.canvas.yview()[0], 0)

    def test_tab_switching_does_not_squish_buttons(self):
        session = self.session
        # Cycle through smaller tabs and back to chaos tab
        for tab in (session.penguin_tab, session.shop_tab, session.event_tab, session.chaos_tab):
            session.mode_notebook.select(tab)
            self.root.update()
        # Ensure chaos_start_btn and controls frame are not vertically compressed
        self.assertGreaterEqual(session.chaos_start_btn.winfo_height(), 28)
        self.assertEqual(session.chaos_start_btn.winfo_height(), session.chaos_start_btn.winfo_reqheight())
        self.assertGreaterEqual(float(session.frame.options.canvas.itemcget(session.frame.options.window, 'height')), session.frame.options.content.winfo_reqheight())


    def test_drag_height_survives_restart_and_keeps_sessions_separate(self):
        frame = self.session.frame
        frame._dragging = True
        frame.panes.sashpos(0, frame.panes.winfo_height() - 285)
        self.root.update()
        frame._finish_drag()
        saved = frame.log_height
        self.assertGreater(saved, 260)
        self.root.update()
        reloaded = LogSplitView(self.root, frame.settings_path, 'session_1')
        other = LogSplitView(self.root, frame.settings_path, 'session_2')
        self.assertEqual(reloaded.log_height, saved)
        self.assertEqual(other.log_height, 220)
        self.root.geometry('800x720'); self.root.update()
        self.assertAlmostEqual(frame.log.winfo_height(), saved, delta=5)
        reloaded.destroy(); other.destroy()

    def test_expand_and_restore_keep_original_height(self):
        frame = self.session.frame
        before = frame.log.winfo_height()
        self.session._toggle_log(); self.root.update()
        self.assertFalse(frame.options.winfo_ismapped())
        self.assertGreater(frame.log.winfo_height(), before)
        reloaded = LogSplitView(self.root, frame.settings_path, 'session_1')
        self.assertTrue(reloaded.expanded)
        reloaded.destroy()
        self.session._toggle_log(); self.root.update()
        self.assertTrue(frame.options.winfo_ismapped())
        self.assertAlmostEqual(frame.log.winfo_height(), before, delta=5)

    def test_mouse_drag_saves_new_height(self):
        frame = self.session.frame
        panes = frame.panes
        start = panes.sashpos(0) + 2
        before = frame.log_height
        panes.event_generate('<ButtonPress-1>', x=100, y=start)
        panes.event_generate('<B1-Motion>', x=100, y=start-45)
        self.root.update()
        panes.event_generate('<ButtonRelease-1>', x=100, y=start-45)
        self.root.update()
        self.assertGreater(frame.log_height, before + 20)
        self.assertTrue(frame.settings_path.is_file())

    def test_bad_saved_layout_falls_back_and_large_height_is_clamped(self):
        path = Path(self.temp.name) / 'invalid.json'
        path.write_text('broken', encoding='utf-8')
        frame = LogSplitView(self.root, path, 'session_1')
        self.assertEqual(frame.log_height, 220)
        frame.destroy()
        frame = self.session.frame
        frame.log_height = 9000
        frame._apply_height(); self.root.update()
        self.assertGreaterEqual(frame.options.winfo_height(), 95)
        self.assertGreaterEqual(frame.log.winfo_height(), 95)


if __name__ == '__main__': unittest.main()
