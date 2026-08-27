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
        items = []
        try:
            while True:
                items.append(self._queue.get_nowait())
        except queue.Empty:
            pass
        if items:
            self._append_many(items)
        self.after(100, self._poll)

    def _append_many(self, items):
        
        
        
        self.text.configure(state=tk.NORMAL)
        anchor = self.text.index('end-1c')
        ts = datetime.now().strftime('%H:%M:%S')
        plain = ''
        ranges = []  
        for message, level in items:
            start = len(plain)
            plain += f'[{ts}] {message}\n'
            ranges.append((start, start + len(ts) + 3, 'info'))
            ranges.append((start + len(ts) + 3, len(plain), level))
        self.text.insert(tk.END, plain)
        for start, end, tag in ranges:
            self.text.tag_add(tag, f'{anchor}+{start}c', f'{anchor}+{end}c')
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

    def busy(self, message: str = ''):
        self._queue.put(('busy', message))

    def reset(self):
        self._queue.put(('reset', 0, 0, ''))

    def _poll(self):
        latest = None
        try:
            while True:
                latest = self._queue.get_nowait()
        except queue.Empty:
            pass
        if latest is not None:
            kind = latest[0]
            if kind == 'busy':
                self._stop_busy()
                self.bar.configure(mode='indeterminate')
                self.bar.start(12)
                self.label.configure(text=latest[1] or '处理中…')
            elif kind == 'set':
                self._stop_busy()
                _, done, total, message = latest
                self.bar.configure(maximum=max(total, 1), value=min(done, total))
                pct = int(done * 100 / total) if total else 0
                self.label.configure(text=message or f'{done}/{total} ({pct}%)')
            else:
                self._stop_busy()
                self.bar.configure(value=0)
                self.label.configure(text='')
        self.after(100, self._poll)

    def _stop_busy(self):
        try:
            self.bar.stop()
        except Exception:
            pass
        self.bar.configure(mode='determinate')
