from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from ..core.pipeline import estimate_job, translate_file
from ..core.usage import UsageLedger
from ..providers import registry
from ..core.workspace import ProjectWorkspace
from .widgets import LogView, ProgressBar

SOURCE_LANGS = ['en', 'zh', 'ja', 'ko', 'fr', 'de', 'es', 'ru', 'auto']
ESTIMATE_CONFIRM_CHUNKS = 50


OPERATION_NAMES = {
    'translate': '翻译',
    'transcribe': '转写',
    'parse': '解析',
}


class OperationDialog(tk.Toplevel):
    def __init__(
        self,
        parent,
        workspace: ProjectWorkspace,
        source_path: str,
        category: str,
        on_done=None,
    ):
        super().__init__(parent)
        self.workspace = workspace
        self.source_path = Path(source_path)
        self.category = category
        self.on_done = on_done
        self._queue = queue.Queue()
        self._records = []
        self._running = False

        self.title(f'{OPERATION_NAMES[category]} · {self.source_path.name}')
        self.geometry('720x620')
        self.minsize(640, 500)
        self.transient(parent)

        body = ttk.Frame(self, padding=14)
        body.pack(fill=tk.BOTH, expand=True)

        provider_frame = ttk.LabelFrame(body, text='供应商', padding=8)
        provider_frame.pack(fill=tk.X)
        self.provider_var = tk.StringVar()
        self.provider_combo = ttk.Combobox(
            provider_frame,
            textvariable=self.provider_var,
            state='readonly',
            width=32,
        )
        self.provider_combo.pack(side=tk.LEFT)
        self.provider_combo.bind('<<ComboboxSelected>>', self._refresh_auth)
        self.auth_label = ttk.Label(provider_frame, text='')
        self.auth_label.pack(side=tk.LEFT, padx=10)

        self.options = ttk.Frame(body)
        self.options.pack(fill=tk.X, pady=(10, 0))
        self._build_options()

        if category == 'transcribe':
            self._build_records(body)

        action_row = ttk.Frame(body)
        action_row.pack(fill=tk.X, pady=10)
        self.start_btn = ttk.Button(
            action_row,
            text=f'开始{OPERATION_NAMES[category]}',
            command=self._start,
        )
        self.start_btn.pack(side=tk.LEFT)
        ttk.Button(action_row, text='关闭', command=self.destroy).pack(
            side=tk.RIGHT
        )

        self.progress = ProgressBar(body)
        self.progress.pack(fill=tk.X, pady=(0, 8))
        self.log = LogView(body, height=8)
        self.log.pack(fill=tk.BOTH, expand=True)

        self._refresh_providers()
        self.after(100, self._poll)

    def _build_options(self):
        for child in self.options.winfo_children():
            child.destroy()
        if self.category == 'translate':
            ttk.Label(self.options, text='源语言').pack(side=tk.LEFT)
            self.source_var = tk.StringVar(value='en')
            ttk.Combobox(
                self.options,
                textvariable=self.source_var,
                state='readonly',
                width=6,
                values=SOURCE_LANGS,
            ).pack(side=tk.LEFT, padx=(4, 8))
            ttk.Label(self.options, text='目标语言').pack(side=tk.LEFT)
            self.lang_var = tk.StringVar(value='zh-Hans')
            ttk.Combobox(
                self.options,
                textvariable=self.lang_var,
                state='readonly',
                width=12,
                values=['zh-Hans', 'zh', 'en'],
            ).pack(side=tk.LEFT, padx=8)
            self.resume_var = tk.BooleanVar(value=True)
            ttk.Checkbutton(
                self.options,
                text='使用断点续传',
                variable=self.resume_var,
            ).pack(side=tk.LEFT, padx=8)
        elif self.category == 'parse':
            ttk.Label(
                self.options,
                text=f'输出目录：{self.workspace.output_dir_for(self.source_path)}',
            ).pack(anchor=tk.W)
        else:
            ttk.Label(
                self.options,
                text=f'输出目录：{self.workspace.output_dir_for(self.source_path)}',
            ).pack(anchor=tk.W)

    def _build_records(self, parent):
        frame = ttk.LabelFrame(parent, text='腾讯会议云录制', padding=8)
        frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        row = ttk.Frame(frame)
        row.pack(fill=tk.X)
        ttk.Button(row, text='加载云录制列表', command=self._load_records).pack(
            side=tk.LEFT
        )
        self.records_hint = ttk.Label(row, text='请选择要导出的录制')
        self.records_hint.pack(side=tk.LEFT, padx=10)
        list_frame = ttk.Frame(frame)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        self.records_list = tk.Listbox(
            list_frame,
            selectmode=tk.EXTENDED,
            font=('Microsoft YaHei UI', 10),
        )
        scroll = ttk.Scrollbar(
            list_frame,
            orient=tk.VERTICAL,
            command=self.records_list.yview,
        )
        self.records_list.configure(yscrollcommand=scroll.set)
        self.records_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def _refresh_providers(self, *_):
        metas = registry.list_by_category(self.category)
        self.provider_combo['values'] = [meta.name for meta in metas]
        if metas:
            configured = registry.default_for(self.category)
            idx = next(
                (
                    i
                    for i, meta in enumerate(metas)
                    if meta.provider_id == configured
                ),
                0,
            )
            self.provider_combo.current(idx)
            self._refresh_auth()

    def _selected_meta(self):
        metas = registry.list_by_category(self.category)
        index = self.provider_combo.current()
        if 0 <= index < len(metas):
            return metas[index]
        return None

    def _provider(self):
        meta = self._selected_meta()
        return registry.get(meta.provider_id) if meta else None

    def _refresh_auth(self, *_):
        provider = self._provider()
        if provider is None:
            self.auth_label.configure(text='没有可用供应商')
            return
        ok, message = provider.validate_auth()
        self.auth_label.configure(
            text=('✓ ' if ok else '✗ ') + message,
            foreground='#2e8b57' if ok else '#b22222',
        )

    def _load_records(self):
        provider = self._provider()
        if provider is None:
            return
        ok, message = provider.validate_auth()
        if not ok:
            messagebox.showerror('转写', message, parent=self)
            return
        self.records_hint.configure(text='加载中...')

        def work():
            try:
                records = provider.list_records()
                self._queue.put(('records', records))
            except Exception as exc:
                self._queue.put(('error', str(exc)))

        threading.Thread(target=work, daemon=True).start()

    def _start(self):
        if self._running:
            return
        provider = self._provider()
        if provider is None:
            return
        ok, message = provider.validate_auth()
        if not ok:
            messagebox.showerror(
                OPERATION_NAMES[self.category],
                message,
                parent=self,
            )
            return
        if not self.source_path.exists():
            messagebox.showerror('工作区', '源文件已经不存在，请刷新项目。', parent=self)
            return
        if self.category == 'translate' and self.source_path.suffix.lower() not in {
            '.md', '.txt', '.tex', '.srt', '.vtt', '.csv', '.json'
        }:
            messagebox.showwarning(
                '翻译',
                '当前翻译管线只支持文本类文档。',
                parent=self,
            )
            return
        if self.category == 'transcribe' and not self._records:
            messagebox.showwarning(
                '转写',
                '请先加载云录制列表并选择录制。',
                parent=self,
            )
            return
        if self.category == 'transcribe' and not self.records_list.curselection():
            messagebox.showwarning(
                '转写',
                '请至少选择一条云录制。',
                parent=self,
            )
            return

        if self.category == 'translate':
            estimate = estimate_job(str(self.source_path), provider)
            if estimate['chunks'] > ESTIMATE_CONFIRM_CHUNKS:
                ledger = UsageLedger(self.workspace.usage_path)
                used = ledger.month_total(provider.meta.provider_id)
                minutes = max(1, round(estimate['seconds'] / 60))
                msg = (
                    f'该文档约 {estimate["chars"]:,} 字符，预计需要 '
                    f'{estimate["chunks"]} 次请求，按当前供应商限速约 '
                    f'{minutes} 分钟。\n'
                    f'本供应商本月已消耗约 {used:,} 字符（免费额度请自行对照）。\n\n'
                    f'确认开始吗？'
                )
                if not messagebox.askyesno('翻译预估', msg, parent=self):
                    return

        self._running = True
        self.start_btn.configure(state=tk.DISABLED)
        self.progress.reset()
        self.workspace.record_action(
            self.source_path,
            self.category,
            'running',
            message='任务已开始',
        )
        if self.category == 'transcribe':
            selected = self.records_list.curselection()
            records = [self._records[i] for i in selected]
            thread = threading.Thread(
                target=self._run_transcribe,
                args=(provider, records),
                daemon=True,
            )
        else:
            thread = threading.Thread(
                target=self._run_file_operation,
                args=(provider,),
                daemon=True,
            )
        thread.start()

    def _run_file_operation(self, provider):
        usage_box = []
        try:
            if self.category == 'translate':
                output = self.workspace.translated_path(self.source_path)
                result = translate_file(
                    str(self.source_path),
                    provider,
                    target_lang=self.lang_var.get(),
                    source_lang=self.source_var.get(),
                    output_path=str(output),
                    resume=self.resume_var.get(),
                    progress_path=str(self.workspace.progress_path),
                    progress_cb=lambda done, total, message: self.progress.set(
                        done, total, message
                    ),
                    usage_cb=lambda chars: usage_box.append(chars),
                )
                outputs = [result]
            else:
                result = provider.process_file(
                    str(self.source_path),
                    str(self.workspace.output_dir_for(self.source_path)),
                )
                outputs = [
                    item.strip()
                    for item in result.split(' + ')
                    if item.strip() and os.path.exists(item.strip())
                ]
            self.workspace.record_action(
                self.source_path,
                self.category,
                'done',
                outputs,
                message='处理完成',
            )
            self._queue.put(('done', outputs))
        except Exception as exc:
            self.workspace.record_action(
                self.source_path,
                self.category,
                'error',
                message=str(exc),
            )
            self._queue.put(('error', str(exc)))
        finally:
            if usage_box:
                UsageLedger(self.workspace.usage_path).record(
                    provider.meta.provider_id, sum(usage_box)
                )

    def _run_transcribe(self, provider, records):
        try:
            results = provider.export_records(
                records,
                str(self.workspace.output_dir_for(self.source_path)),
            )
            outputs = []
            failures = []
            for result in results:
                if 'chars' in result:
                    segment = result.get('seg', '')
                    output = self.workspace.output_dir_for(self.source_path) / (
                        f'{segment}-总结.md'
                    )
                    outputs.append(str(output))
                if 'error' in result:
                    failures.append(
                        f"{result.get('seg', '未知录制')}: {result['error']}"
                    )
            if failures and not outputs:
                raise RuntimeError('\n'.join(failures))
            self.workspace.record_action(
                self.source_path,
                self.category,
                'done',
                outputs,
                message=f'完成 {len(outputs)} 条',
            )
            self._queue.put(('done', outputs, failures))
        except Exception as exc:
            self.workspace.record_action(
                self.source_path,
                self.category,
                'error',
                message=str(exc),
            )
            self._queue.put(('error', str(exc)))

    def _poll(self):
        try:
            while True:
                item = self._queue.get_nowait()
                kind = item[0]
                if kind == 'records':
                    self._records = item[1]
                    self.records_list.delete(0, tk.END)
                    for record in self._records:
                        self.records_list.insert(
                            tk.END,
                            record.get('title', record.get('record_id', '未命名')),
                        )
                    self.records_hint.configure(
                        text=f'共 {len(self._records)} 条，支持多选'
                    )
                elif kind == 'done':
                    outputs = item[1]
                    failures = item[2] if len(item) > 2 else []
                    self._running = False
                    self.start_btn.configure(state=tk.NORMAL)
                    self.progress.set(1, 1, '全部完成')
                    self.log.log(f'完成，生成 {len(outputs)} 个文件', 'success')
                    for failure in failures:
                        self.log.log(f'失败：{failure}', 'error')
                    if self.on_done:
                        self.on_done()
                elif kind == 'error':
                    self._running = False
                    self.start_btn.configure(state=tk.NORMAL)
                    self.log.log(item[1], 'error')
                    messagebox.showerror(
                        OPERATION_NAMES[self.category],
                        item[1],
                        parent=self,
                    )
        except queue.Empty:
            pass
        self.after(100, self._poll)


def open_operation(
    parent,
    workspace: ProjectWorkspace,
    source_path: str,
    category: str,
    on_done=None,
):
    return OperationDialog(
        parent,
        workspace,
        source_path,
        category,
        on_done=on_done,
    )
