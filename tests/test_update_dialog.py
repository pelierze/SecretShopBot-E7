import tkinter as tk
import unittest
from unittest.mock import Mock

from src.release_checker import ReleaseInfo
from src.update_dialog import UpdateConfirmationDialog


class UpdateDialogTests(unittest.TestCase):
    def show(self, body, install=False):
        root = tk.Tk()
        self.addCleanup(root.destroy)
        release = ReleaseInfo('v9.0.0', 'https://example.com', '새 버전', body)
        open_page = Mock()
        observed = {}

        def respond():
            dialog = next(w for w in root.winfo_children()
                          if isinstance(w, UpdateConfirmationDialog))
            observed['body'] = dialog.notes.get('1.0', 'end-1c')
            observed['state'] = dialog.notes.cget('state')
            observed['view'] = dialog.notes.yview()
            if install:
                dialog.install_button.invoke()
            else:
                dialog.cancel()

        root.after(100, respond)
        dialog = UpdateConfirmationDialog(root, release, '1.5.5', open_page)
        open_page.assert_not_called()
        return dialog, observed

    def test_long_notes_are_read_only_scrollable_and_cancel_does_not_confirm(self):
        body = '\n'.join(f'- 변경사항 {i}' for i in range(80))
        dialog, observed = self.show(body)
        self.assertEqual(observed['body'], body)
        self.assertEqual(observed['state'], 'disabled')
        self.assertLess(observed['view'][1], 1)
        self.assertFalse(dialog.confirmed)

    def test_empty_notes_have_fallback_and_only_install_confirms(self):
        dialog, observed = self.show('  ', install=True)
        self.assertIn('등록되지 않았습니다', observed['body'])
        self.assertTrue(dialog.confirmed)
