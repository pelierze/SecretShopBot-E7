import logging
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from src.gui import TextHandler

class LogThreadingTest(unittest.TestCase):
    def setUp(self):
        self.owner=threading.get_ident()
        self.widget=Mock()
        def require_gui(*args,**kwargs):
            if threading.get_ident()!=self.owner:
                raise AssertionError("Tk was called from a logging worker")
            return 'timer'
        self.widget.after.side_effect=require_gui
        self.widget.bind.side_effect=require_gui
        self.widget.configure.side_effect=require_gui
        self.widget.insert.side_effect=require_gui
        self.widget.after_cancel.side_effect=require_gui
        self.widget.yview.return_value=(0,1)
        self.handler=TextHandler(self.widget,'test')
        self.addCleanup(self.handler.close)

    def record(self,text,session='test'):
        r=logging.LogRecord('test',logging.INFO,__file__,1,text,(),None)
        r.session_name=session
        return r

    def test_worker_log_returns_without_calling_tk_or_waiting_for_gui(self):
        errors=[]
        def worker():
            try:
                self.handler.handle(self.record('worker message'))
            except Exception as e:
                errors.append(e)
        thread=threading.Thread(target=worker,daemon=True)
        thread.start();thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors,[])
        self.widget.after.assert_called_once()
        self.widget.insert.assert_not_called()
        self.handler._drain()
        self.assertIn('worker message',self.widget.insert.call_args.args[1])

    def test_busy_gui_can_log_while_worker_enqueues(self):
        thread=threading.Thread(target=lambda: self.handler.handle(self.record('worker')),daemon=True)
        thread.start()
        self.handler.handle(self.record('GUI'))
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.handler._drain()
        text=self.widget.insert.call_args.args[1]
        self.assertIn('worker',text)
        self.assertIn('GUI',text)

    def test_session_filter_and_batch_limit(self):
        self.handler.handle(self.record('excluded','other'))
        for i in range(105):
            self.handler.handle(self.record(str(i)))
        self.handler._drain()
        text=self.widget.insert.call_args.args[1]
        self.assertNotIn('excluded',text)
        self.assertEqual(len(text.splitlines()),100)
        self.assertEqual(self.handler._messages.qsize(),5)

    def test_destroyed_widget_never_receives_future_logs(self):
        self.handler._on_destroy(SimpleNamespace(widget=self.widget))
        self.handler.handle(self.record('late'))
        self.handler._drain()
        self.widget.insert.assert_not_called()
        self.widget.after_cancel.assert_called_once()
