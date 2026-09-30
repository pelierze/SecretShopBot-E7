"""Scrollable Tk content with wheel routing confined to its own descendants."""
import tkinter as tk
from tkinter import ttk


class ScrollableFrame(ttk.Frame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0,
                                background='#efe7dc', width=1, height=1)
        self.vertical = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        self.horizontal = ttk.Scrollbar(self, orient='horizontal', command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=self.vertical.set, xscrollcommand=self.horizontal.set)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        self.vertical.grid(row=0, column=1, sticky='ns')
        self.horizontal.grid(row=1, column=0, sticky='ew')
        self.content = ttk.Frame(self)
        self.window = self.canvas.create_window(0, 0, window=self.content, anchor='nw')
        self.content.bind('<Configure>', self._resize, add='+')
        self.canvas.bind('<Configure>', self._resize, add='+')
        self._tag = f'ScrollArea{id(self)}'
        for sequence in ('<MouseWheel>', '<Shift-MouseWheel>', '<Button-4>', '<Button-5>'):
            self.bind_class(self._tag, sequence, self._wheel)
        self.bind_class(self._tag, '<FocusIn>', self._focus)
        self.bind('<Destroy>', self._destroy_bindings, add='+')
        self._current_size = None

    def _resize(self, _event=None):
        if not self.canvas.winfo_exists() or not self.content.winfo_exists():
            return
        width = max(self.canvas.winfo_width(), self.content.winfo_reqwidth())
        height = max(self.canvas.winfo_height(), self.content.winfo_reqheight())
        if self._current_size == (width, height):
            return
        self._current_size = (width, height)
        self.canvas.itemconfigure(self.window, width=width, height=height)
        self.canvas.configure(scrollregion=(0, 0, width, height))

    def bind_children(self):
        def visit(widget):
            if self._tag not in widget.bindtags():
                widget.bindtags((self._tag, *widget.bindtags()))
            for child in widget.winfo_children():
                visit(child)
        visit(self.content)
        self.canvas.bindtags((self._tag, *self.canvas.bindtags()))

    def _wheel(self, event):
        horizontal = bool(event.state & 0x1)
        delta = getattr(event, 'delta', 0)
        direction = -1 if delta > 0 or getattr(event, 'num', None) == 4 else 1
        # Log text keeps its native wheel until it reaches its boundary.
        if isinstance(event.widget, tk.Text) and not horizontal:
            first, last = event.widget.yview()
            if (direction < 0 and first > 0) or (direction > 0 and last < 1):
                return None
        scroll = self.canvas.xview_scroll if horizontal else self.canvas.yview_scroll
        scroll(direction * max(1, abs(int(delta / 120))) * 3, 'units')
        return 'break'

    def _focus(self, event):
        widget = event.widget
        if widget in (self.content, self.canvas) or not widget.winfo_ismapped():
            return
        # Keyboard traversal should reveal controls that are outside the viewport.
        for axis, position, size, viewport, extent in (
            ('x', widget.winfo_rootx() - self.content.winfo_rootx(), widget.winfo_width(), self.canvas.winfo_width(), self.content.winfo_width()),
            ('y', widget.winfo_rooty() - self.content.winfo_rooty(), widget.winfo_height(), self.canvas.winfo_height(), self.content.winfo_height()),
        ):
            view = self.canvas.xview if axis == 'x' else self.canvas.yview
            move = self.canvas.xview_moveto if axis == 'x' else self.canvas.yview_moveto
            start = view()[0] * extent
            if position < start:
                move(max(0, position - 8) / extent)
            elif position + size > start + viewport:
                move(max(0, position + size + 8 - viewport) / extent)

    def _destroy_bindings(self, event):
        if event.widget is self:
            for sequence in ('<MouseWheel>', '<Shift-MouseWheel>', '<Button-4>', '<Button-5>', '<FocusIn>'):
                self.unbind_class(self._tag, sequence)
