import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from ..core.config import config
from ..core.runtime import runtime_dir
from ..providers import registry


class ConfigDialog(tk.Toplevel):
    KEYS = [
        ('TENCENT_SECRET_ID', '腾讯 SecretId'),
        ('TENCENT_SECRET_KEY', '腾讯 SecretKey'),
        ('BAIDU_APP_ID', '百度 APP ID'),
        ('BAIDU_KEY', '百度 Key'),
        ('MINERU_TOKEN', 'MinerU Token'),
    ]

    def __init__(self, parent, on_saved=None):
        super().__init__(parent)
        self.on_saved = on_saved
        self.title('配置')
        self.geometry('560x600')
        self.transient(parent)
        self._queue = queue.Queue()

        body = ttk.Frame(self, padding=16)
        body.pack(fill=tk.BOTH, expand=True)

        auth_frame = ttk.LabelFrame(body, text='腾讯会议登录态', padding=10)
        auth_frame.pack(fill=tk.X)
        self.auth_label = ttk.Label(auth_frame, text='')
        self.auth_label.pack(anchor=tk.W)
        btn_row = ttk.Frame(auth_frame)
        btn_row.pack(fill=tk.X, pady=(6, 0))
        self.import_btn = ttk.Button(btn_row, text='从桌面客户端导入',
                                     command=self._import_desktop)
        self.import_btn.pack(side=tk.LEFT)
        self.login_btn = ttk.Button(btn_row, text='网页扫码登录',
                                    command=self._login)
        self.login_btn.pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_row, text='手动粘贴 Cookie',
                   command=self._paste_cookies).pack(side=tk.LEFT)
        self._refresh_auth()

        self.key_frame = ttk.LabelFrame(body, text='API 密钥', padding=10)
        self.key_frame.pack(fill=tk.X, pady=(12, 0))
        self._build_keys()

        ai_frame = ttk.LabelFrame(body, text='AI 润色', padding=10)
        ai_frame.pack(fill=tk.X, pady=(12, 0))
        ok, msg = self._claude_status()
        ttk.Label(ai_frame, text=('✓ ' if ok else '✗ ') + msg,
                  foreground='#2e8b57' if ok else '#b22222').pack(anchor=tk.W)
        self.test_text = tk.Text(ai_frame, height=5, font=('Consolas', 9),
                                 state=tk.DISABLED, bg='#f5f5f5')
        self.test_text.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        self.test_btn = ttk.Button(ai_frame, text='测试全部',
                                   command=self._test_all)
        self.test_btn.pack(anchor=tk.E, pady=(6, 0))

        self.after(100, self._poll)

    def _build_keys(self):
        for w in self.key_frame.winfo_children():
            w.destroy()
        self.key_rows = {}
        for row, (key, label) in enumerate(self.KEYS):
            self.key_rows[key] = self._build_key_row(
                self.key_frame, key, label, row)
        ttk.Button(self.key_frame, text='保存密钥',
                   command=self._save_keys).grid(
            row=len(self.KEYS), column=1, sticky=tk.E, pady=(8, 0))

    def _build_key_row(self, parent, key, label, row):
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=0, columnspan=2, sticky=tk.EW, pady=2)
        state_label = ttk.Label(frame, text=label)
        state_label.grid(row=0, column=0, sticky=tk.W)
        entry = ttk.Entry(frame, width=36, show='*')
        edit_btn = ttk.Button(frame, text='修改')

        def show_entry():
            entry.delete(0, tk.END)
            entry.insert(0, config.get(key))
            entry.grid(row=0, column=1, padx=6, sticky=tk.EW)
            edit_btn.grid_forget()

        if config.has(key):
            done = ttk.Label(frame, text='✓ 已配置', foreground='#2e8b57')
            done.grid(row=0, column=1, sticky=tk.W, padx=6)
            edit_btn.configure(command=show_entry)
            edit_btn.grid(row=0, column=2, padx=4)
        else:
            need = ttk.Label(frame, text='✗ 需要手动补全',
                             foreground='#b22222')
            need.grid(row=0, column=2, padx=4)
            entry.grid(row=0, column=1, padx=6, sticky=tk.EW)
        frame.columnconfigure(1, weight=1)
        return {'frame': frame, 'entry': entry,
                'has_visible_entry': lambda: entry.winfo_ismapped()}

    def _provider(self):
        return registry.get('wemeet')

    def _claude_status(self):
        from ..ai import polish as ai
        return ai.detect_claude()

    def _refresh_auth(self):
        ok, msg = self._provider().validate_auth()
        self.auth_label.configure(
            text=('✓ ' if ok else '✗ ') + msg,
            foreground='#2e8b57' if ok else '#b22222')

    def _save_keys(self):
        for key, row in self.key_rows.items():
            entry = row['entry']
            if entry.winfo_ismapped():
                value = entry.get().strip()
                if value:
                    config.set(key, value)
        if self.on_saved:
            self.on_saved()
        self._build_keys()

    def _import_desktop(self):
        self.import_btn.configure(state=tk.DISABLED)

        def work():
            try:
                ok, msg = self._provider().import_desktop_cookies()
                self._queue.put(('auth', ok, msg))
            except Exception as e:
                self._queue.put(('error', str(e)))
        threading.Thread(target=work, daemon=True).start()

    def _login(self):
        self.login_btn.configure(state=tk.DISABLED)
        self._qr_shown = False
        self._qr_watch_started = None

        def work():
            try:
                ok = self._provider().login()
                self._queue.put(('login', ok))
            except Exception as e:
                self._queue.put(('error', str(e)))
        threading.Thread(target=work, daemon=True).start()
        self._watch_qr()

    def _watch_qr(self):
        from pathlib import Path
        import os
        qr = runtime_dir() / 'wemeet_qr.png'
        if qr.exists() and not self._qr_shown:
            self._qr_shown = True
            from .preview import show_image
            show_image(self, str(qr), '扫码登录')
        if self.login_btn.cget('state') == tk.DISABLED and not self._qr_shown:
            self.after(1000, self._watch_qr)

    def _paste_cookies(self):
        dialog = tk.Toplevel(self)
        dialog.title('粘贴 Cookie')
        dialog.geometry('560x300')
        dialog.transient(self)
        text = tk.Text(dialog, height=10, font=('Consolas', 10))
        text.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        def do_save():
            ok, msg = self._provider().import_cookies_from_text(
                text.get('1.0', 'end').strip())
            messagebox.showinfo('配置', msg, parent=dialog)
            if ok:
                dialog.destroy()
                self._refresh_auth()
        btn_row = ttk.Frame(dialog)
        btn_row.pack(fill=tk.X, padx=12, pady=(0, 12))
        ttk.Button(btn_row, text='保存', command=do_save).pack(side=tk.RIGHT)
        ttk.Button(btn_row, text='取消',
                   command=dialog.destroy).pack(side=tk.RIGHT, padx=8)

    def _test_all(self):
        self.test_btn.configure(state=tk.DISABLED)

        def work():
            try:
                lines = []
                for cat in ('translate', 'transcribe', 'parse'):
                    for meta in registry.list_by_category(cat):
                        provider = registry.get(meta.provider_id)
                        ok, msg = provider.validate_auth()
                        lines.append(f'{"✓" if ok else "✗"} {meta.name}: {msg}')
                for meta in registry.list_by_category('translate'):
                    provider = registry.get(meta.provider_id)
                    ok, _ = provider.validate_auth()
                    if ok:
                        try:
                            result = provider._translate(
                                'The electric field is the force per unit charge.',
                                'zh-Hans')
                            lines.append(f'  {meta.name} 实测: {result}')
                        except Exception as e:
                            lines.append(f'  {meta.name} 实测失败: {e}')
                self._queue.put(('test', lines))
            except Exception as e:
                self._queue.put(('error', str(e)))
        threading.Thread(target=work, daemon=True).start()

    def _poll(self):
        try:
            while True:
                item = self._queue.get_nowait()
                kind = item[0]
                if kind == 'auth':
                    _, ok, msg = item
                    self.import_btn.configure(state=tk.NORMAL)
                    messagebox.showinfo('配置', msg, parent=self)
                    self._refresh_auth()
                elif kind == 'login':
                    _, ok = item
                    self.login_btn.configure(state=tk.NORMAL)
                    messagebox.showinfo('配置',
                                        '登录成功，cookies 已保存'
                                        if ok else '登录失败/超时',
                                        parent=self)
                    self._refresh_auth()
                elif kind == 'test':
                    _, lines = item
                    self.test_btn.configure(state=tk.NORMAL)
                    self.test_text.configure(state=tk.NORMAL)
                    self.test_text.delete('1.0', tk.END)
                    self.test_text.insert('1.0', '\n'.join(lines))
                    self.test_text.configure(state=tk.DISABLED)
                elif kind == 'error':
                    _, msg = item
                    self.import_btn.configure(state=tk.NORMAL)
                    self.login_btn.configure(state=tk.NORMAL)
                    self.test_btn.configure(state=tk.NORMAL)
                    messagebox.showerror('配置', msg, parent=self)
        except queue.Empty:
            pass
        self.after(100, self._poll)


def open_config(parent, on_saved=None):
    return ConfigDialog(parent, on_saved)
