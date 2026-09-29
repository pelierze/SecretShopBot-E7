"""Independent scrollable options and persistent, resizable log pane."""
import json
import logging
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from .scrollable_frame import ScrollableFrame

logger = logging.getLogger(__name__)


class LogSplitView(ttk.Frame):
    def __init__(self, parent, settings_path, session_id):
        super().__init__(parent)
        self.settings_path = Path(settings_path)
        self.session_id = session_id
        saved = self._read().get(session_id, {})
        if not isinstance(saved, dict):
            saved = {}
        height = saved.get('log_height', 220)
        self.log_height = height if type(height) is int and 80 <= height <= 10000 else 220
        self.expanded = saved.get('expanded') is True
        self._dragging = False
        self._pending_resize = None
        self.panes = ttk.Panedwindow(self, orient=tk.VERTICAL)
        self.panes.pack(fill=tk.BOTH, expand=True)
        self.options = ScrollableFrame(self.panes)
        self.log = ttk.Frame(self.panes, style='Card.TFrame', padding=10)
        if not self.expanded:
            self.panes.add(self.options, weight=1)
        self.panes.add(self.log, weight=0)
        self.panes.bind('<Configure>', self._resize, add='+')
        self.panes.bind('<Map>', self._resize, add='+')
        self.panes.bind('<ButtonPress-1>', self._start_drag, add='+')
        self.panes.bind('<ButtonRelease-1>', self._finish_drag, add='+')
        self.log.bind('<Configure>', self._resize, add='+')
        self.bind('<Destroy>', self._destroy, add='+')

    def _read(self):
        try:
            values = json.loads(self.settings_path.read_text(encoding='utf-8'))
            return values if isinstance(values, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self):
        try:
            values = self._read()
            values[self.session_id] = {'log_height': self.log_height, 'expanded': self.expanded}
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.settings_path.with_suffix('.tmp')
            temporary.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding='utf-8')
            temporary.replace(self.settings_path)
        except OSError:
            logger.exception('로그 영역 크기 저장 실패')

    def _resize(self, _event=None):
        if not self._dragging and self._pending_resize is None:
            self._pending_resize = self.after_idle(self._apply_height)

    def _apply_height(self):
        self._pending_resize = None
        if not self.winfo_exists() or self.expanded or self._dragging:
            return
        height = self.panes.winfo_height()
        if height < 10:
            return
        gap = 6  # Standard ttk sash; keep geometry independent of pending layouts.
        minimum = min(100, height // 3)
        log_height = min(max(minimum, self.log_height), max(minimum, height - minimum - gap))
        position = max(minimum, height - log_height - gap)
        if self.panes.sashpos(0) != position:
            self.panes.sashpos(0, position)

    def _start_drag(self, event):
        self._dragging = not self.expanded and self.panes.identify(event.x, event.y) != ''

    def _finish_drag(self, _event=None):
        if self._dragging:
            self.update_idletasks()
            self.log_height = max(80, self.log.winfo_height())
            self._dragging = False
            self._apply_height()
            self._save()

    def toggle_log(self):
        if self.expanded:
            self.panes.insert(0, self.options, weight=1)
        else:
            self.panes.forget(self.options)
        self.expanded = not self.expanded
        self._save()
        self._resize()

    def _destroy(self, event):
        if event.widget is self and self._pending_resize is not None:
            self.after_cancel(self._pending_resize)
            self._pending_resize = None
