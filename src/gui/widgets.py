import queue
import tkinter as tk
from datetime import datetime
from tkinter import ttk


class LogView(ttk.LabelFrame):
    def __init__(self, parent, height=4):
        super().__init__(parent, text='日志', padding=4)
        self.text = tk.Text(self, height=height, wrap=tk.WORD,
                            state=tk.DISABLED, font=('Consolas', 10),
                            bg='#1e1e1e', fg='#d4d4d4')
        scrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL,
                                  command=self.text.yview)
        self.text.configure(yscrollcommand=scrollbar.set)
        self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.text.tag_configure('info', foreground='#d4d4d4')
        self.text.tag_configure('success', foreground='#4ec9b0')
        self.text.tag_configure('warning', foreground='#ce9178')
        self.text.tag_configure('error', foreground='#f44747')

        self._queue = queue.Queue()
        self.after(100, self._poll)

    def log(self, message: str, level: str = 'info'):
        self._queue.put((message, level))

    def _poll(self):
        try:
            while True:
                message, level = self._queue.get_nowait()
                self._append(message, level)
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _append(self, message, level):
        self.text.configure(state=tk.NORMAL)
        ts = datetime.now().strftime('%H:%M:%S')
        self.text.insert(tk.END, f'[{ts}] ', 'info')
        self.text.insert(tk.END, message + '\n', level)
        self.text.see(tk.END)
        self.text.configure(state=tk.DISABLED)

    def clear(self):
        self.text.configure(state=tk.NORMAL)
        self.text.delete('1.0', tk.END)
        self.text.configure(state=tk.DISABLED)


class ProgressBar(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.bar = ttk.Progressbar(self, mode='determinate')
        self.bar.pack(fill=tk.X, side=tk.LEFT, expand=True, padx=(0, 8))
        self.label = ttk.Label(self, text='', width=32, anchor=tk.E)
        self.label.pack(side=tk.RIGHT)

        self._queue = queue.Queue()
        self.after(100, self._poll)

    def set(self, done: int, total: int, message: str = ''):
        self._queue.put(('set', done, total, message))

    def reset(self):
        self._queue.put(('reset', 0, 0, ''))

    def _poll(self):
        try:
            while True:
                item = self._queue.get_nowait()
                if item[0] == 'set':
                    _, done, total, message = item
                    self.bar.configure(maximum=max(total, 1),
                                       value=min(done, total))
                    pct = int(done * 100 / total) if total else 0
                    self.label.configure(
                        text=message or f'{done}/{total} ({pct}%)')
                else:
                    self.bar.configure(value=0)
                    self.label.configure(text='')
        except queue.Empty:
            pass
        self.after(100, self._poll)
