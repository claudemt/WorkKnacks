from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from ..core.pipeline import estimate_job
from ..core.usage import UsageLedger
from ..core.workspace import ProjectWorkspace
from ..library.operations import has_parsed_latex, parse_document, translate_document
from ..providers import registry
from .layout import fit_window
from .widgets import LogView, ProgressBar


ESTIMATE_CONFIRM_CHUNKS = 50
OPERATION_NAMES = {'translate': '翻译'}
TARGET_LANGS = {'中文': 'zh-Hans', 'English': 'en'}


class OperationDialog(tk.Toplevel):
    

    def __init__(self, parent, workspace: ProjectWorkspace, source_path: str, category: str, on_done=None):
        super().__init__(parent)
        self.workspace = workspace
        self.source_path = Path(source_path)
        self.category = category
        self.on_done = on_done
        self._queue = queue.Queue()
        self._running = False
        self.parse_btn = None

        self.title(f'{OPERATION_NAMES[category]} · {self.source_path.name}')
        fit_window(self, 720, 560, min_width=600, min_height=460)
        self.transient(parent)

        body = ttk.Frame(self, padding=14)
        body.pack(fill=tk.BOTH, expand=True)

        if category == 'translate':
            options = ttk.Frame(body)
            options.pack(fill=tk.X)
            ttk.Label(options, text='目标语言').pack(side=tk.LEFT)
            self.lang_display_var = tk.StringVar(value='中文')
            self.lang_combo = ttk.Combobox(
                options, textvariable=self.lang_display_var,
                values=list(TARGET_LANGS), state='readonly', width=12,
            )
            self.lang_combo.pack(side=tk.LEFT, padx=(8, 0))

        action_row = ttk.Frame(body)
        action_row.pack(fill=tk.X, pady=(12, 8))
        self.parse_btn = None
        self.arxiv_btn = None
        has_parse_buttons = False
        if category == 'translate' and self.source_path.suffix.lower() == '.pdf':
            self.parse_btn = ttk.Button(action_row, text='解析', command=self._start_parse)
            self.parse_btn.pack(side=tk.LEFT)
            self.arxiv_btn = ttk.Button(action_row, text='用 arXiv 源码', command=self._start_parse_arxiv)
            self.arxiv_btn.pack(side=tk.LEFT, padx=(8, 0))
            has_parse_buttons = True
        self.start_btn = ttk.Button(action_row, text=f'开始{OPERATION_NAMES[category]}', command=self._start)
        self.start_btn.pack(side=tk.LEFT, padx=(8 if has_parse_buttons else 0, 0))
        ttk.Button(action_row, text='关闭', command=self.destroy).pack(side=tk.RIGHT)

        self.progress = ProgressBar(body)
        self.progress.pack(fill=tk.X, pady=(0, 8))
        self.log = LogView(body, height=8)
        self.log.pack(fill=tk.BOTH, expand=True)
        self.after(100, self._poll)

    def _provider(self):
        provider_id = registry.default_for(self.category)
        if not provider_id:
            metas = registry.list_by_category(self.category)
            provider_id = metas[0].provider_id if metas else ''
        provider = registry.get(provider_id) if provider_id else None
        if provider is None:
            metas = registry.list_by_category(self.category)
            provider = registry.get(metas[0].provider_id) if metas else None
        return provider

    def _require_provider(self):
        provider = self._provider()
        if provider is None:
            raise RuntimeError(f'没有可用的{OPERATION_NAMES[self.category]}服务。请点击主界面“配置”完成服务配置。')
        ok, message = provider.validate_auth()
        if not ok:
            raise RuntimeError(message + '\n\n请点击主界面“配置”完成服务配置。')
        return provider

    def _start_parse(self):
        self._begin_parse(arxiv_only=False)

    def _start_parse_arxiv(self):
        self._begin_parse(arxiv_only=True)

    def _begin_parse(self, arxiv_only: bool):
        if self._running:
            return
        if self.source_path.suffix.lower() != '.pdf':
            return
        if not self.source_path.exists():
            messagebox.showerror('解析', '源文件已经不存在，请刷新项目。', parent=self)
            return
        if has_parsed_latex(self.source_path):
            if not messagebox.askyesno(
                '重新解析',
                '已经存在解析结果。重新解析会更新 parsed/ 中的 main.tex、main.pdf 和 figures/。继续吗？',
                parent=self,
            ):
                return
        if not arxiv_only:
            provider_id = registry.default_for('parse') or 'mineru'
            provider = registry.get(provider_id)
            if provider is None:
                messagebox.showerror('解析', '没有可用的 MinerU 解析服务。请点击主界面“配置”。', parent=self)
                return
            ok, message = provider.validate_auth()
            if not ok:
                messagebox.showerror('解析', message + '\n\n请点击主界面“配置”完成 MinerU 配置。', parent=self)
                return

        self._running = True
        self.start_btn.configure(state=tk.DISABLED)
        for btn in (self.parse_btn, self.arxiv_btn):
            if btn is not None:
                btn.configure(state=tk.DISABLED)
        self.progress.reset()
        label = '用 arXiv 源码解析' if arxiv_only else 'MinerU 解析'
        self.workspace.record_action(self.source_path, 'parse', 'running', message=label + ' 任务已开始')
        self.log.log(('正在从 arXiv 下载 TeX 源码…' if arxiv_only else '尝试从 arXiv 获取源码，失败则回退 MinerU；完成后会自动进行一轮 AI 解析校对。'))
        threading.Thread(target=lambda: self._run_parse(arxiv_only), daemon=True).start()

    def _run_parse(self, arxiv_only=False):
        try:
            arxiv_id = ''
            title = ''
            authors = []
            year = None
            try:
                from ..library.index import LibraryIndex
                entry = LibraryIndex(self.workspace.root).entry_for_path(self.source_path)
                if entry:
                    arxiv_id = entry.arxiv_id
                    title = entry.title
                    year = entry.year or None
                    authors = [
                        f'{author.given or ""} {author.family or ""}'.strip()
                        for author in entry.authors
                        if author.family or author.given
                    ]
            except Exception:
                arxiv_id = ''
            tex_path = parse_document(
                self.source_path,
                project_root=self.workspace.root,
                status_cb=lambda text: self._queue.put(('status', text)),
                arxiv_id=arxiv_id,
                arxiv_only=arxiv_only,
                title=title,
                authors=authors,
                year=year,
            )
            outputs = [str(tex_path)]
            pdf_path = tex_path.with_name('main.pdf')
            if pdf_path.exists():
                outputs.append(str(pdf_path))
            self.workspace.record_action(self.source_path, 'parse', 'done', outputs, message='解析完成')
            self._queue.put(('parsed', outputs))
        except Exception as exc:
            self.workspace.record_action(self.source_path, 'parse', 'error', message=str(exc))
            self._queue.put(('error', str(exc)))

    def _start(self):
        if self._running:
            return
        try:
            provider = self._require_provider()
        except Exception as exc:
            messagebox.showerror(OPERATION_NAMES[self.category], str(exc), parent=self)
            return
        if not self.source_path.exists():
            messagebox.showerror('工作区', '源文件已经不存在，请刷新项目。', parent=self)
            return
        if self.category == 'translate' and self.source_path.suffix.lower() not in {
            '.pdf', '.md', '.txt', '.tex', '.srt', '.vtt', '.csv', '.json'
        }:
            messagebox.showwarning('翻译', '当前翻译支持 PDF 与文本类文档。', parent=self)
            return

        if self.category == 'translate' and self.source_path.suffix.lower() == '.pdf' and not has_parsed_latex(self.source_path):
            messagebox.showwarning(
                '翻译',
                '该 PDF 尚未解析。请先点击本窗口的“解析”按钮，确认解析完成后再开始翻译。',
                parent=self,
            )
            return

        if self.category == 'translate' and self.source_path.suffix.lower() != '.pdf':
            estimate = estimate_job(str(self.source_path), provider)
            if estimate['chunks'] > ESTIMATE_CONFIRM_CHUNKS:
                minutes = max(1, round(estimate['seconds'] / 60))
                if not messagebox.askyesno(
                    '翻译',
                    f'这份文档较长，预计约 {estimate["chunks"]} 次请求 / {minutes} 分钟。继续吗？',
                    parent=self,
                ):
                    return

        self._running = True
        self.start_btn.configure(state=tk.DISABLED)
        if self.parse_btn is not None:
            self.parse_btn.configure(state=tk.DISABLED)
        self.progress.reset()
        self.workspace.record_action(self.source_path, self.category, 'running', message='任务已开始')
        threading.Thread(target=self._run_file_operation, args=(provider,), daemon=True).start()

    def _run_file_operation(self, provider):
        usage_box = []
        try:
            outputs = []
            target_lang = TARGET_LANGS.get(self.lang_display_var.get(), 'zh-Hans')
            result = translate_document(
                self.source_path,
                provider,
                target_lang=target_lang,
                source_lang='auto',
                resume=True,
                progress_path=str(self.workspace.progress_path),
                progress_cb=lambda done, total, message: self.progress.set(done, total, message),
                usage_cb=lambda chars: usage_box.append(chars),
                project_root=self.workspace.root,
                polish=True,
            )
            outputs.append(str(result))
            self.workspace.record_action(self.source_path, self.category, 'done', outputs, message='处理完成')
            self._queue.put(('done', outputs))
        except Exception as exc:
            self.workspace.record_action(self.source_path, self.category, 'error', message=str(exc))
            self._queue.put(('error', str(exc)))
        finally:
            if usage_box:
                UsageLedger(self.workspace.usage_path).record(provider.meta.provider_id, sum(usage_box))

    def _poll(self):
        try:
            while True:
                item = self._queue.get_nowait()
                kind = item[0]
                if kind == 'log':
                    self.log.log(str(item[1]))
                elif kind == 'status':
                    self.progress.busy(str(item[1]))
                elif kind == 'done':
                    outputs = item[1]
                    failures = item[2] if len(item) > 2 else []
                    self._running = False
                    self.start_btn.configure(state=tk.NORMAL)
                    if self.parse_btn is not None:
                        self.parse_btn.configure(state=tk.NORMAL)
                    self.progress.set(1, 1, '完成')
                    self.log.log('完成')
                    if failures:
                        self.log.log('\n'.join(failures))
                    if self.on_done:
                        self.on_done(outputs)
                elif kind == 'parsed':
                    outputs = item[1]
                    self._running = False
                    self.start_btn.configure(state=tk.NORMAL)
                    if self.parse_btn is not None:
                        self.parse_btn.configure(state=tk.NORMAL)
                    self.progress.set(1, 1, '解析完成')
                    self.log.log('解析完成：' + ', '.join(Path(value).name for value in outputs))
                    if self.on_done:
                        
                        
                        self.on_done([])
                elif kind == 'error':
                    self._running = False
                    self.start_btn.configure(state=tk.NORMAL)
                    if self.parse_btn is not None:
                        self.parse_btn.configure(state=tk.NORMAL)
                    self.log.log(str(item[1]))
                    messagebox.showerror(OPERATION_NAMES[self.category], str(item[1]), parent=self)
        except queue.Empty:
            pass
        self.after(100, self._poll)


def open_operation(parent, workspace, source_path, category, on_done=None):
    return OperationDialog(parent, workspace, source_path, category, on_done)
