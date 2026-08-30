from __future__ import annotations

import tkinter as tk


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
