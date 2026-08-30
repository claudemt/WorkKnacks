from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from ..core.workspace import ProjectWorkspace
from ..library.operations import has_parsed_latex, parse_document
from ..providers import registry
from .layout import fit_window
from .widgets import LogView, ProgressBar

ENGINES = [
    ('arxiv', 'arXiv 源码'),
    ('mineru', 'MinerU'),
]


class ParseDialog(tk.Toplevel):
    """Standalone 解析 dialog with an explicit engine choice (arXiv / MinerU).

    Runs ``parse_document`` on the selected file. arXiv re-downloads the real
    TeX source (best when available); MinerU runs pure OCR/MD parsing. Logs
    every step so the user can see what happened.
    """

    def __init__(self, parent, workspace: ProjectWorkspace, source_path: str, on_done=None):
        super().__init__(parent)
        self.workspace = workspace
        self.source_path = Path(source_path)
        self.on_done = on_done
        self._queue = queue.Queue()
        self._running = False

        self.title(f'解析 · {self.source_path.name}')
        fit_window(self, 720, 560, min_width=600, min_height=460)
        self.transient(parent)

        body = ttk.Frame(self, padding=14)
        body.pack(fill=tk.BOTH, expand=True)

        engine_row = ttk.Frame(body)
        engine_row.pack(fill=tk.X)
        ttk.Label(engine_row, text='解析引擎').pack(side=tk.LEFT)
        self.engine_var = tk.StringVar(value='arxiv')
        for value, label in ENGINES:
            ttk.Radiobutton(
                engine_row, text=label, value=value, variable=self.engine_var
            ).pack(side=tk.LEFT, padx=(10, 0))

        hint = ttk.Label(
            body,
            text='arXiv：从 arXiv 下载作者原始 TeX 源码（效果最好）；MinerU：本地 PDF→Markdown/LaTeX 解析。',
            foreground='#666666',
        )
        hint.pack(fill=tk.X, pady=(4, 0))

        action_row = ttk.Frame(body)
        action_row.pack(fill=tk.X, pady=(12, 8))
        self.start_btn = ttk.Button(action_row, text='开始解析', command=self._start)
        self.start_btn.pack(side=tk.LEFT)
        ttk.Button(action_row, text='关闭', command=self.destroy).pack(side=tk.RIGHT)

        self.progress = ProgressBar(body)
        self.progress.pack(fill=tk.X, pady=(0, 8))
        self.log = LogView(body, height=11)
        self.log.pack(fill=tk.BOTH, expand=True)
        self.log.log(f'准备解析：{self.source_path.name}')
        self.after(100, self._poll)

    def _entry_hints(self):
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
        return arxiv_id, title, authors, year

    def _start(self):
        if self._running:
            return
        if not self.source_path.exists():
            messagebox.showerror('解析', '源文件已经不存在，请刷新项目。', parent=self)
            return
        engine = self.engine_var.get()
        if has_parsed_latex(self.source_path):
            if not messagebox.askyesno(
                '重新解析',
                '已经存在解析结果。重新解析会更新 parsed/ 中的 main.tex、main.pdf 和 figures/。继续吗？',
                parent=self,
            ):
                return
        if engine == 'mineru':
            provider_id = registry.default_for('parse') or 'mineru'
            provider = registry.get(provider_id)
            if provider is None:
                messagebox.showerror('解析', '没有可用的 MinerU 解析服务。请点击主界面“设置”。', parent=self)
                return
            ok, message = provider.validate_auth()
            if not ok:
                messagebox.showerror('解析', message + '\n\n请点击主界面“设置”完成 MinerU 配置。', parent=self)
                return

        self._running = True
        self.start_btn.configure(state=tk.DISABLED)
        self.progress.reset()
        label = {'arxiv': '用 arXiv 源码解析', 'mineru': 'MinerU 解析'}[engine]
        self.log.log(f'任务已开始：{label}')
        self.workspace.record_action(self.source_path, 'parse', 'running', message=f'{label} 任务已开始')
        threading.Thread(target=lambda: self._run(engine), daemon=True).start()

    def _run(self, engine):
        try:
            from src.library.artifacts import ArtifactLayout
            from src.library.history import HistoryStore
            try:
                _layout = ArtifactLayout.for_source(self.source_path)
                HistoryStore(self.workspace.root).before_mutation(
                    [_layout.parse_dir, Path(self.source_path).parent / 'citation.bib'],
                    None,
                )
            except Exception:
                pass  # 快照失败不阻塞解析
            arxiv_id, title, authors, year = self._entry_hints()

            arxiv_only = engine == 'arxiv'
            prefer_arxiv = engine == 'arxiv'
            tex_path = parse_document(
                self.source_path,
                project_root=self.workspace.root,
                status_cb=lambda text: self._queue.put(('status', text)),
                arxiv_id=arxiv_id,
                arxiv_only=arxiv_only,
                prefer_arxiv=prefer_arxiv,
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

    def _poll(self):
        try:
            while True:
                item = self._queue.get_nowait()
                kind = item[0]
                if kind == 'status':
                    text = str(item[1])
                    self.progress.busy(text)
                    self.log.log(text)
                elif kind == 'parsed':
                    self._running = False
                    self.start_btn.configure(state=tk.NORMAL)
                    self.progress.set(1, 1, '解析完成')
                    self.log.log('解析完成：' + ', '.join(Path(value).name for value in item[1]))
                    if self.on_done:
                        self.on_done(item[1])
                elif kind == 'error':
                    self._running = False
                    self.start_btn.configure(state=tk.NORMAL)
                    self.log.log(str(item[1]))
                    messagebox.showerror('解析', str(item[1]), parent=self)
        except queue.Empty:
            pass
        self.after(100, self._poll)


def open_parse(parent, workspace: ProjectWorkspace, source_path: str, on_done=None):
    return ParseDialog(parent, workspace, source_path, on_done)
