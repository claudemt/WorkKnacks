from __future__ import annotations

import queue
import shutil
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from src.core.config import config
from src.providers import registry

from .layout import fit_window


def _wipe_dir(directory: Path) -> int:
    if not directory.exists() or not directory.is_dir():
        return 0
    count = 0
    for item in directory.iterdir():
        try:
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            else:
                item.unlink(missing_ok=True)
            count += 1
        except OSError:
            pass
    return count


TRANSLATION_PROVIDERS = [
    ('deepl_oneshot', 'DeepL'),
]
PROVIDER_ID_TO_NAME = dict(TRANSLATION_PROVIDERS)
PROVIDER_NAME_TO_ID = {name: provider_id for provider_id, name in TRANSLATION_PROVIDERS}


class ConfigDialog(tk.Toplevel):


    def __init__(self, parent, on_saved=None):
        super().__init__(parent)
        self.on_saved = on_saved
        self._queue: queue.Queue = queue.Queue()
        self._testing = False
        self.title('设置')
        fit_window(self, 660, 560, min_width=560, min_height=500)
        self.transient(parent)

        body = ttk.Frame(self, padding=16)
        body.pack(fill=tk.BOTH, expand=True)

        self._build_mineru(body)
        self._build_latex(body)
        self._build_translation(body)
        self._build_cache(body)
        self._build_history(body)

        footer = ttk.Frame(body)
        footer.pack(fill=tk.X, pady=(14, 0))
        self.test_btn = ttk.Button(footer, text='检测接口', command=self._test)
        self.test_btn.pack(side=tk.LEFT)
        ttk.Button(footer, text='取消', command=self.destroy).pack(side=tk.RIGHT)
        ttk.Button(footer, text='保存', command=self._save).pack(side=tk.RIGHT, padx=(0, 8))

        self.after(100, self._poll)

    def _build_mineru(self, parent):
        frame = ttk.LabelFrame(parent, text='MinerU', padding=12)
        frame.pack(fill=tk.X)
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text='Token').grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
        self.mineru_token = ttk.Entry(frame, show='•')
        self.mineru_token.grid(row=0, column=1, sticky=tk.EW)
        self.mineru_token.insert(0, config.get('MINERU_TOKEN'))

        self.mineru_status = ttk.Label(frame, text='')
        self.mineru_status.grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(8, 0))
        self.after(80, self._refresh_status)

    def _build_latex(self, parent):
        frame = ttk.LabelFrame(parent, text='LaTeX 编译器', padding=12)
        frame.pack(fill=tk.X, pady=(12, 0))
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text='编译器 bin 目录').grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
        self.tex_bin_entry = ttk.Entry(frame)
        self.tex_bin_entry.grid(row=0, column=1, sticky=tk.EW)
        self.tex_bin_entry.insert(0, config.get('TEX_BIN_DIR'))

    def _build_translation(self, parent):
        frame = ttk.LabelFrame(parent, text='翻译', padding=12)
        frame.pack(fill=tk.BOTH, expand=True, pady=(12, 0))
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text='默认服务').grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
        current_id = config.get('DEFAULT_PROVIDER_TRANSLATE', 'deepl_oneshot') or 'deepl_oneshot'
        current_name = PROVIDER_ID_TO_NAME.get(current_id, 'DeepL')
        self.translate_provider = tk.StringVar(value=current_name)
        combo = ttk.Combobox(
            frame,
            textvariable=self.translate_provider,
            values=[name for _, name in TRANSLATION_PROVIDERS],
            state='readonly',
            width=22,
        )
        combo.grid(row=0, column=1, sticky=tk.W)
        combo.bind('<<ComboboxSelected>>', lambda _e: self._show_translation_fields())

        self.translation_fields = ttk.Frame(frame)
        self.translation_fields.grid(row=1, column=0, columnspan=2, sticky=tk.NSEW, pady=(10, 0))
        self.translation_fields.columnconfigure(1, weight=1)
        frame.rowconfigure(1, weight=1)

        self._entries: dict[str, ttk.Entry] = {}
        self.translation_status = ttk.Label(frame, text='')
        self.translation_status.grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=(10, 0))
        self._show_translation_fields()

    def _build_cache(self, parent):
        frame = ttk.LabelFrame(parent, text='清理缓存', padding=12)
        frame.pack(fill=tk.X, pady=(12, 0))
        row = ttk.Frame(frame)
        row.pack(fill=tk.X)
        self._cache_vars: dict[str, tk.BooleanVar] = {}
        for key, label in (('ai', 'AI记录'), ('state', '文件状态')):
            var = tk.BooleanVar(value=False)
            self._cache_vars[key] = var
            ttk.Checkbutton(row, text=label, variable=var).pack(side=tk.LEFT, padx=(0, 20))
        ttk.Button(row, text='清理', command=self._clean_cache).pack(side=tk.RIGHT)

    def _build_history(self, parent):
        frame = ttk.LabelFrame(parent, text='实时备份', padding=12)
        frame.pack(fill=tk.X, pady=(12, 0))
        self.realtime_var = tk.BooleanVar(value=config.get_int('REALTIME_BACKUP', 1) == 1)
        ttk.Checkbutton(frame, text='实时创建副本（每次改动本地文件夹前自动保存，供「撤回」使用）', variable=self.realtime_var).pack(anchor=tk.W)

    def _clean_cache(self):
        workspace = getattr(self.master, 'workspace', None)
        if not workspace:
            messagebox.showwarning('清理缓存', '请先打开一个项目。', parent=self)
            return
        ai = self._cache_vars['ai'].get()
        state = self._cache_vars['state'].get()
        if not (ai or state):
            messagebox.showinfo('清理缓存', '请至少勾选一类缓存。', parent=self)
            return
        targets = []
        if ai:
            targets.extend([workspace.session_dir, workspace.backup_dir])
        if state:
            targets.extend([workspace.paths.cache, workspace.paths.state])
        removed = sum(_wipe_dir(directory) for directory in targets)
        messagebox.showinfo('清理缓存', f'已清理 {removed} 个文件。', parent=self)

    def _add_field(self, parent, row: int, key: str, label: str, *, secret: bool = False, default: str = ''):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky=tk.W, padx=(0, 10), pady=4)
        entry = ttk.Entry(parent, show='•' if secret else '')
        entry.grid(row=row, column=1, sticky=tk.EW, pady=4)
        entry.insert(0, config.get(key, default))
        self._entries[key] = entry

    def _show_translation_fields(self):
        for child in self.translation_fields.winfo_children():
            child.destroy()
        self._entries = {}
        ttk.Label(self.translation_fields, text='DeepL 无需 API Key。').grid(row=0, column=0, sticky=tk.W)
        self._refresh_status()

    def _save_values(self):
        provider_id = PROVIDER_NAME_TO_ID.get(self.translate_provider.get(), 'deepl_oneshot')
        values = {
            'DEFAULT_PROVIDER_PARSE': 'mineru',
            'DEFAULT_PROVIDER_TRANSLATE': provider_id,
            'MINERU_TOKEN': self.mineru_token.get().strip(),
            'TEX_BIN_DIR': self.tex_bin_entry.get().strip(),
            'REALTIME_BACKUP': '1' if self.realtime_var.get() else '0',
        }
        for key, entry in self._entries.items():
            values[key] = entry.get().strip()
        config.set_many(values)

    def _save(self):
        try:
            self._save_values()
        except Exception as exc:
            messagebox.showerror('设置', str(exc), parent=self)
            return
        if self.on_saved:
            self.on_saved()
        self._refresh_status()
        messagebox.showinfo('设置', '已保存到 config/.env.local', parent=self)

    def _refresh_status(self):
        try:
            mineru = registry.get('mineru')
            ok, message = mineru.validate_auth() if mineru else (False, 'MinerU provider 未加载')
            self.mineru_status.configure(text=('✓ ' if ok else '✗ ') + message)
        except Exception as exc:
            self.mineru_status.configure(text='✗ ' + str(exc))

        try:
            provider_id = PROVIDER_NAME_TO_ID.get(self.translate_provider.get(), 'deepl_oneshot')
            provider = registry.get(provider_id)
            ok, message = provider.validate_auth() if provider else (False, '翻译 provider 未加载')
            self.translation_status.configure(text=('✓ ' if ok else '✗ ') + message)
        except Exception as exc:
            self.translation_status.configure(text='✗ ' + str(exc))

    def _test(self):
        if self._testing:
            return
        try:
            self._save_values()
        except Exception as exc:
            messagebox.showerror('设置', str(exc), parent=self)
            return
        self._testing = True
        self.test_btn.configure(state=tk.DISABLED)

        def work():
            results = []
            try:
                mineru = registry.get('mineru')
                ok, message = mineru.check_connectivity() if mineru else (False, 'provider 未加载')
                results.append(f'MinerU: {"可用" if ok else "不可用"} · {message}')
            except Exception as exc:
                results.append(f'MinerU: 检测失败 · {exc}')

            provider_id = PROVIDER_NAME_TO_ID.get(self.translate_provider.get(), 'deepl_oneshot')
            try:
                provider = registry.get(provider_id)
                ok, message = provider.check_connectivity() if provider else (False, 'provider 未加载')
                results.append(f'{PROVIDER_ID_TO_NAME.get(provider_id, provider_id)}: {"可用" if ok else "不可用"} · {message}')
            except Exception as exc:
                results.append(f'{PROVIDER_ID_TO_NAME.get(provider_id, provider_id)}: 检测失败 · {exc}')

            try:
                from src.providers.parse.mineru import _which_tex
                exe = _which_tex('xelatex') or _which_tex('latexmk') or _which_tex('pdflatex')
                results.append(f'LaTeX: {"可用" if exe else "未找到"} · {exe or "请安装或指定 TEX_BIN_DIR"}')
            except Exception as exc:
                results.append(f'LaTeX: 检测失败 · {exc}')

            try:
                import ssl
                import urllib.request
                ctx = ssl.create_default_context()
                url = 'https://api.openalex.org/works?per-page=1&mailto=workknacks@localhost'
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 WorkKnacks/3.0'})
                with urllib.request.urlopen(req, timeout=8, context=ctx) as r:
                    results.append(f'OpenAlex: {"可用" if r.status == 200 else "限流"} · HTTP {r.status}')
            except urllib.error.HTTPError as exc:
                results.append(f'OpenAlex: 限流/异常 · HTTP {exc.code}')
            except Exception as exc:
                results.append(f'OpenAlex: 不可达 · {type(exc).__name__}')
            self._queue.put(results)

        threading.Thread(target=work, daemon=True).start()

    def _poll(self):
        try:
            while True:
                results = self._queue.get_nowait()
                self._testing = False
                self.test_btn.configure(state=tk.NORMAL)
                self._refresh_status()
                messagebox.showinfo('接口检测', '\n'.join(results), parent=self)
        except queue.Empty:
            pass
        self.after(100, self._poll)


def open_config(parent, on_saved=None):
    return ConfigDialog(parent, on_saved=on_saved)
