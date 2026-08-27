from __future__ import annotations

import tkinter as tk
from tkinter import ttk


def fit_window(
    window: tk.Misc,
    preferred_width: int,
    preferred_height: int,
    *,
    min_width: int = 560,
    min_height: int = 420,
    horizontal_margin: int = 40,
    vertical_margin: int = 90,
) -> tuple[int, int]:
    

    window.update_idletasks()
    screen_w = max(640, int(window.winfo_screenwidth()))
    screen_h = max(480, int(window.winfo_screenheight()))
    usable_w = max(520, screen_w - horizontal_margin)
    usable_h = max(380, screen_h - vertical_margin)
    width = max(min(preferred_width, usable_w), min(min_width, usable_w))
    height = max(min(preferred_height, usable_h), min(min_height, usable_h))
    window.minsize(min(min_width, usable_w), min(min_height, usable_h))
    x = max(0, (screen_w - width) // 2)
    y = max(0, (screen_h - height) // 2)
    window.geometry(f'{width}x{height}+{x}+{y}')
    return width, height


class VerticalScrolledFrame(ttk.Frame):
    

    def __init__(self, parent, *, padding=0):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        self.scrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas, padding=padding)
        self.window_id = self.canvas.create_window((0, 0), window=self.inner, anchor='nw')
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.inner.bind('<Configure>', self._sync_scrollregion)
        self.canvas.bind('<Configure>', self._sync_width)
        self.canvas.bind('<Enter>', self._bind_wheel)
        self.canvas.bind('<Leave>', self._unbind_wheel)

    def _sync_scrollregion(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox('all'))

    def _sync_width(self, event):
        self.canvas.itemconfigure(self.window_id, width=max(1, event.width))

    def _bind_wheel(self, _event=None):
        self.canvas.bind_all('<MouseWheel>', self._on_mousewheel)
        self.canvas.bind_all('<Button-4>', self._on_linux_wheel)
        self.canvas.bind_all('<Button-5>', self._on_linux_wheel)

    def _unbind_wheel(self, _event=None):
        self.canvas.unbind_all('<MouseWheel>')
        self.canvas.unbind_all('<Button-4>')
        self.canvas.unbind_all('<Button-5>')

    def _on_mousewheel(self, event):
        delta = int(-event.delta / 120) if event.delta else 0
        if delta:
            self.canvas.yview_scroll(delta, 'units')

    def _on_linux_wheel(self, event):
        self.canvas.yview_scroll(-1 if event.num == 4 else 1, 'units')
