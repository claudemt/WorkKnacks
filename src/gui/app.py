from __future__ import annotations

import os
import queue
import shutil
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from src.core.config import config
from src.core.osutils import open_path, reveal_path
from src.core.project_paths import ProjectPaths
from src.core.workspace import ProjectWorkspace
from src.library.ai_note import generate_note
from src.library.artifacts import ArtifactLayout, artifact_relpath
from src.library.archive import archive_pdf, archive_supplement, rename_archived_entry
from src.library.entry import LibraryEntry, normalize_doi
from src.library.fetch import MetadataFetcher
from src.library.index import LibraryIndex
from src.library.md_export import md_to_pdf
from src.library.md_server import MarkdownServer
from src.library.recovery import MetadataRecoveryService
from src.library.biblio import write_citation_bundle

from . import docs_viewer
from .agent_panel import AgentPanel
from .batch_dialog import BatchDialog
from .config_dialog import open_config
from .entry_dialog import show_entry_dialog
from .explorer import ExplorerView
from .layout import fit_window
from .operation_dialog import open_operation


class MainWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('WorkKnacks · 文献工作台')
        fit_window(self, 1440, 860, min_width=900, min_height=620)
        self._fullscreen = False
        self._windowed_geometry = self.geometry()
        self.bind('<F11>', self._toggle_fullscreen)
        self.bind('<Escape>', self._escape_fullscreen)
        self.bind('<F2>', self._rename_selected)
        self.workspace: ProjectWorkspace | None = None
        self.library_index: LibraryIndex | None = None
        self.current_rel = ''
        self.md_server: MarkdownServer | None = None
        self._queue: queue.Queue = queue.Queue()
        self._info_review_reports: dict[str, object] = {}
        self._info_fetch_results: dict[str, object] = {}
        self._selected: Path | None = None
        self._build_layout()
        self.after(120, self._poll)

        remembered = config.get('LAST_PROJECT')
        if remembered and Path(remembered).is_dir():
            self._set_workspace(remembered)
        else:
            self._show_empty()

    def _build_layout(self):
        header = ttk.Frame(self, padding=(14, 10, 14, 6))
        header.pack(fill=tk.X)
        title_row = ttk.Frame(header)
        title_row.pack(fill=tk.X)
        ttk.Label(title_row, text='WorkKnacks', font=('Segoe UI', 18, 'bold')).pack(side=tk.LEFT)

        toolbar = ttk.Frame(header)
        toolbar.pack(fill=tk.X, pady=(7, 0))
        ttk.Button(toolbar, text='打开项目', command=self._open_project).pack(side=tk.LEFT, padx=2)
        self.up_btn = ttk.Button(toolbar, text='上级', command=self._go_up, state=tk.DISABLED)
        self.up_btn.pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text='刷新', command=self._refresh_workspace).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text='批量', command=self._open_batch).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text='配置', command=lambda: open_config(self, self._refresh_workspace)).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text='帮助', command=lambda: docs_viewer.open_docs('index')).pack(side=tk.RIGHT, padx=2)

        ttk.Separator(self).pack(fill=tk.X)
        project_bar = ttk.Frame(self, padding=(14, 8))
        project_bar.pack(fill=tk.X)
        self.project_name = ttk.Label(project_bar, text='尚未打开项目', font=('Microsoft YaHei UI', 12, 'bold'))
        self.project_name.grid(row=0, column=0, sticky=tk.W)
        self.nav_label = ttk.Label(project_bar, text='/', anchor=tk.W)
        self.nav_label.grid(row=0, column=1, sticky=tk.EW, padx=12)
        project_bar.columnconfigure(1, weight=1)

        search_frame = ttk.Frame(self, padding=(14, 0, 14, 8))
        search_frame.pack(fill=tk.X)
        ttk.Label(search_frame, text='搜索').grid(row=0, column=0, sticky=tk.W)
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(search_frame, textvariable=self.search_var)
        self.search_entry.grid(row=0, column=1, sticky=tk.EW, padx=(6, 0))
        self.search_entry.bind('<KeyRelease>', lambda _e: self._refresh_workspace())
        search_frame.columnconfigure(1, weight=1)

        self.empty = ttk.Frame(self, padding=40)
        ttk.Label(self.empty, text='打开一个文件夹，把它作为文献项目', font=('Microsoft YaHei UI', 16, 'bold')).pack(pady=(100, 8))

        self.panes = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        self.main_pane = ttk.Frame(self.panes, width=620)
        self.agent_panel = AgentPanel(self.panes, on_files_changed=self._refresh_workspace)
        self.agent_panel.configure(width=360)
        self.panes.add(self.main_pane, weight=3)
        self.panes.add(self.agent_panel, weight=2)
        self.panes.bind('<Configure>', self._ensure_reasonable_sash, add='+')

        self.explorer = ExplorerView(self.main_pane, self._handle_action, self._select_path)
        self.explorer.pack(fill=tk.BOTH, expand=True, padx=(14, 8), pady=(0, 8))


    def _toggle_fullscreen(self, _event=None):
        entering = not self._fullscreen
        if entering:
            self._windowed_geometry = self.geometry()
        self._fullscreen = entering
        self.attributes('-fullscreen', self._fullscreen)
        if self._fullscreen:
            self.geometry(f'{self.winfo_screenwidth()}x{self.winfo_screenheight()}+0+0')
        elif self._windowed_geometry:
            self.geometry(self._windowed_geometry)
        return 'break'

    def _escape_fullscreen(self, _event=None):
        if self._fullscreen:
            self._fullscreen = False
            self.attributes('-fullscreen', False)
            if self._windowed_geometry:
                self.geometry(self._windowed_geometry)
            return 'break'
        return None

    def _ensure_reasonable_sash(self, _event=None):
        if not self.panes.winfo_ismapped():
            return
        width = self.panes.winfo_width()
        if width < 10:
            return
        try:
            current = self.panes.sashpos(0)
        except tk.TclError:
            return
        
        
        
        min_main = min(620, max(520, width - 380))
        min_agent = min(430, max(350, width // 3))
        lower = min_main
        upper = max(lower, width - min_agent)
        if current < lower:
            self.panes.sashpos(0, lower)
        elif current > upper:
            self.panes.sashpos(0, upper)

    def _set_default_sash(self):
        if not self.panes.winfo_ismapped():
            return
        width = self.panes.winfo_width()
        if width < 100:
            return
        
        target = max(520, min(int(width * 0.62), width - 350))
        try:
            self.panes.sashpos(0, target)
        except tk.TclError:
            return

    def _show_empty(self):
        self.panes.pack_forget()
        self.empty.pack(fill=tk.BOTH, expand=True)
        self.project_name.configure(text='尚未打开项目')
        self.nav_label.configure(text='/')
        self.agent_panel.set_workspace(None)

    def _set_workspace(self, root):
        try:
            workspace = ProjectWorkspace(root).ensure()
            index = LibraryIndex(workspace.root)
            index.self_heal()
        except Exception as exc:
            messagebox.showerror('项目文件夹', str(exc), parent=self)
            return
        if self.md_server:
            self.md_server.stop()
        self.md_server = None
        self.workspace = workspace
        self.library_index = index
        self.current_rel = ''
        config.set('LAST_PROJECT', str(workspace.root))
        self.project_name.configure(text=workspace.root.name or str(workspace.root))
        self.empty.pack_forget()
        self.panes.pack(fill=tk.BOTH, expand=True)
        self.agent_panel.set_workspace(workspace.root)
        self.after_idle(self._set_default_sash)
        self.after(80, self._set_default_sash)
        self.after(220, self._set_default_sash)
        self._refresh_workspace()

    def _open_project(self):
        selected = filedialog.askdirectory(title='选择项目文件夹', mustexist=True)
        if selected:
            self._set_workspace(selected)

    def _refresh_workspace(self):
        if not self.workspace or not self.library_index:
            self._show_empty()
            return
        self.workspace.state = self.workspace._load_state()
        self.library_index.reload()
        folders, docs = self.workspace.list_dir(self.current_rel)
        query = self.search_var.get().strip().casefold()
        if query:
            folders = [p for p in folders if query in p.name.casefold()]
            matched_ids = {entry.id for entry in self.library_index.search(query)}
            filtered = []
            for path in docs:
                if query in path.name.casefold():
                    filtered.append(path)
                    continue
                entry = self.library_index.entry_for_path(path)
                if entry and entry.id in matched_ids:
                    filtered.append(path)
            docs = filtered
        self.explorer.render(self.workspace, folders, docs, self.library_index)
        self.up_btn.configure(state=tk.NORMAL if self.current_rel else tk.DISABLED)
        self.nav_label.configure(text='/' + self.current_rel if self.current_rel else '/')

    def _go_up(self):
        if not self.current_rel:
            return
        self.current_rel = Path(self.current_rel).parent.as_posix()
        if self.current_rel == '.':
            self.current_rel = ''
        self._refresh_workspace()

    def _enter_folder(self, path: Path):
        if not self.workspace:
            return
        self.current_rel = self.workspace.relative_path(path)
        self._refresh_workspace()

    def _select_path(self, path: Path):
        self._selected = path


    def _handle_action(self, action: str, path: Path):
        if not self.workspace:
            return
        try:
            if action == 'enter':
                self._enter_folder(path)
            elif action == 'folder_edit':
                self._edit_folder(path)
            elif action == 'new_note':
                self._new_note(path)
            elif action == 'view':
                self._view(path)
            elif action == 'info':
                self._open_info(path)
            elif action == 'translate':
                open_operation(
                    self, self.workspace, str(path), action,
                    on_done=lambda outputs=None, p=path, a=action: self._operation_done(p, a, outputs or []),
                )
            elif action == 'ai':
                self.agent_panel.insert_file(path)
            elif action == 'summarize':
                self._start_ai_note(path)
            elif action == 'md_export':
                self._start_md_export(path)
            elif action == 'md_edit':
                self._markdown_server().open_edit(path)
            elif action == 'polish':
                self.agent_panel.prepare_file_task(path, skill='polish', prompt='请润色这个文件，保持原意、术语和 Markdown/LaTeX 结构；如需修改文件请直接编辑并让我确认 diff。')
            elif action == 'send_ai':
                self.agent_panel.insert_file(path)
            elif action == 'copy_path':
                self.clipboard_clear(); self.clipboard_append(str(path.resolve()))
            elif action == 'reveal':
                reveal_path(path)
            elif action == 'rename':
                self._rename(path)
            elif action == 'delete':
                self._delete(path)
        except Exception as exc:
            messagebox.showerror('WorkKnacks', str(exc), parent=self)

    def _view(self, path: Path):
        if path.suffix.lower() in {'.md', '.markdown'}:
            self._markdown_server().open_view(path)
        else:
            open_path(path)

    def _operation_done(self, source: Path, action: str, outputs: list[str]) -> None:
        
        if not self.library_index or not source.exists():
            self._refresh_workspace()
            return
        entry = self.library_index.entry_for_path(source)
        if not entry:
            self._refresh_workspace()
            return
        attachment = next(
            (item for item in entry.attachments if item.path and Path(item.path).name == source.name),
            None,
        )
        if attachment is None:
            self._refresh_workspace()
            return

        if action == 'translate':
            parse_dir = ArtifactLayout.for_source(source).parse_dir
            if parse_dir.exists():
                attachment.artifacts['parseDir'] = artifact_relpath(source.parent, parse_dir)
            rels: list[str] = []
            for value in outputs:
                candidate = Path(value).expanduser().resolve()
                try:
                    rels.append(artifact_relpath(source.parent, candidate))
                except ValueError:
                    continue
            if rels:
                previous = list(attachment.artifacts.get('translations') or [])
                attachment.artifacts['translations'] = list(dict.fromkeys([*previous, *rels]))

        if attachment.role == 'primary':
            if attachment.artifacts.get('parseDir'):
                entry.files['parseDir'] = attachment.artifacts['parseDir']
            if attachment.artifacts.get('translations'):
                entry.files['translations'] = attachment.artifacts['translations']
                entry.files.pop('translation', None)
        self.library_index.upsert(entry)
        if entry.folder:
            write_citation_bundle(self.library_index.root / entry.folder, entry)
        self._refresh_workspace()

    def _markdown_server(self) -> MarkdownServer:
        if not self.workspace:
            raise RuntimeError('未打开项目')
        if not self.md_server:
            self.md_server = MarkdownServer(self.workspace.root).start()
        return self.md_server

    def _open_info(self, path: Path, *, auto_on_open: bool | None = None):
        if path.suffix.lower() != '.pdf' or not self.library_index or not self.workspace:
            return
        existing = self.library_index.entry_for_path(path)
        initial = LibraryEntry.from_dict(existing.to_dict()) if existing else LibraryEntry(title=path.stem, item_type='document')
        if auto_on_open is None:
            auto_on_open = existing is None
        confirmed = show_entry_dialog(
            self,
            initial,
            title='信息',
            auto_recognize=self._make_auto_recognize(path),
            ai_review=self._make_ai_review(path),
            auto_on_open=bool(auto_on_open),
        )
        if confirmed:
            self._commit_info(path, confirmed, existing)

    def _make_auto_recognize(self, path: Path):
        root = self.workspace.root if self.workspace else path.parent
        cache_dir = ProjectPaths.for_root(root).metadata_cache

        def recognize():
            result = MetadataFetcher(cache_dir=cache_dir).fetch(path, allow_local_parse=False)
            self._info_fetch_results[str(path.resolve())] = result
            entry = result.entry
            if not entry or not entry.title or result.source == 'local':
                return None, '常规学术数据库未命中。可手工填写，或在少数困难文献上使用 AI复核。'
            role = '补充材料' if result.supplement.is_supplement else '主文献'
            summary = '\n'.join(filter(None, [
                f'识别：{role} · {result.source}',
                f'标题：{entry.title}',
                f'作者：{", ".join(c.display() for c in entry.authors[:4]) or "—"}',
                f'年份：{entry.year or "—"}',
                f'DOI / arXiv / ISBN：{entry.doi or entry.arxiv_id or entry.isbn or "—"}',
            ]))
            return LibraryEntry.from_dict(entry.to_dict()), summary
        return recognize

    def _make_ai_review(self, path: Path):
        root = self.workspace.root if self.workspace else path.parent

        def review():
            report = MetadataRecoveryService(root).recover(path, pages=6, use_ai=True)
            self._info_review_reports[str(path.resolve())] = report
            candidate = report.recommended
            entry = candidate.entry if candidate else report.local_entry
            parts = []
            if candidate:
                parts.append(f'推荐来源：{candidate.source}')
            if report.ai_used:
                parts.append(f'AI 置信度：{report.ai_confidence:.0%}')
                if report.ai_reason:
                    parts.append(f'理由：{report.ai_reason}')
            parts.extend([
                f'标题：{entry.title or "—"}',
                f'作者：{", ".join(c.display() for c in entry.authors[:4]) or "—"}',
                f'年份：{entry.year or "—"}',
                f'DOI / arXiv / ISBN：{entry.doi or entry.arxiv_id or entry.isbn or "—"}',
            ])
            return LibraryEntry.from_dict(entry.to_dict()), '\n'.join(parts)
        return review

    def _commit_info(self, path: Path, confirmed: LibraryEntry, existing: LibraryEntry | None):
        if not self.workspace or not self.library_index or not path.exists():
            return
        key = str(path.resolve())
        fetch_result = self._info_fetch_results.pop(key, None)
        report = self._info_review_reports.pop(key, None)
        supplement = getattr(report, 'supplement', None) or getattr(fetch_result, 'supplement', None)
        mapping = self.library_index.mapping_for(path) or {}

        if existing and mapping.get('status') in {'organized', 'supplement'}:
            confirmed = self._preserve_entry_identity(existing, confirmed)
            self._save_existing_info(path, confirmed)
            return

        folder_parent = next((
            entry for entry in self.library_index.entries()
            if entry.folder and (self.library_index.root / entry.folder).resolve() == path.parent.resolve()
        ), None)
        contextual_supplement = False
        if not (supplement and supplement.is_supplement) and folder_parent and not mapping:
            same_doi = bool(confirmed.doi and folder_parent.doi and confirmed.doi.strip().casefold() == folder_parent.doi.strip().casefold())
            same_title = bool(confirmed.title and folder_parent.title and confirmed.title.strip().casefold() == folder_parent.title.strip().casefold())
            if same_doi or same_title:
                contextual_supplement = messagebox.askyesno(
                    '信息',
                    '这个未登记 PDF 位于已识别文献文件夹中，并且识别结果指向同一母文章。\n是否作为 Supplementary Materials 加入该条目？',
                    parent=self,
                )
                if contextual_supplement:
                    confirmed = LibraryEntry.from_dict(folder_parent.to_dict())

        if (supplement and supplement.is_supplement) or contextual_supplement:
            
            
            
            if supplement and supplement.is_supplement and folder_parent and not mapping:
                detected_parent_doi = normalize_doi(supplement.parent_doi or '')
                current_parent_doi = normalize_doi(folder_parent.doi or '')
                if detected_parent_doi and current_parent_doi and detected_parent_doi != current_parent_doi:
                    if not messagebox.askyesno(
                        '信息',
                        '补充材料识别出的母文章 DOI 与当前文献文件夹不同。\n'
                        '仍要把它作为当前文献的 Supplementary Materials 吗？',
                        parent=self,
                    ):
                        return
                confirmed = LibraryEntry.from_dict(folder_parent.to_dict())
            try:
                result = archive_supplement(
                    self.workspace.root,
                    path,
                    confirmed,
                    index=self.library_index,
                    parent_doi=(folder_parent.doi if folder_parent else '') or (supplement.parent_doi if supplement else ''),
                    supplement_doi=getattr(fetch_result, 'doi', '') or extract_doi_safe(getattr(report, 'preview_text', '')),
                )
            except Exception as exc:
                messagebox.showerror('信息', str(exc), parent=self)
                return
            self._refresh_workspace()
            messagebox.showinfo('信息', f'已作为补充材料加入：\n{result.folder.name}', parent=self)
            return

        duplicate, reason, score = self.library_index.find_duplicate(confirmed)
        if duplicate and duplicate.id != confirmed.id and duplicate.files.get('pdf'):
            if not messagebox.askyesno(
                '信息',
                f'可能与已有条目重复（{reason}, {score:.0%}）：\n{duplicate.title}\n\n仍然归档吗？',
                parent=self,
            ):
                return
        try:
            result = archive_pdf(self.workspace.root, path, confirmed, index=self.library_index)
        except Exception as exc:
            messagebox.showerror('信息', str(exc), parent=self)
            return
        self._refresh_workspace()
        messagebox.showinfo('信息', f'已保存：\n{result.folder.name}', parent=self)

    @staticmethod
    def _preserve_entry_identity(existing: LibraryEntry, incoming: LibraryEntry) -> LibraryEntry:
        incoming.id = existing.id
        incoming.folder = existing.folder
        incoming.files = dict(existing.files)
        incoming.attachments = list(existing.attachments)
        incoming.ai_note = dict(existing.ai_note)
        if not incoming.tags:
            incoming.tags = list(existing.tags)
        if not incoming.keywords:
            incoming.keywords = list(existing.keywords)
        incoming.reading_status = incoming.reading_status or existing.reading_status
        return incoming

    def _save_existing_info(self, path: Path, edited: LibraryEntry):
        if not self.library_index or not self.workspace:
            return
        self.library_index.upsert(edited)
        try:
            if edited.folder and (edited.files.get('pdf') or edited.supplementary_attachments):
                rename_archived_entry(self.workspace.root, edited, index=self.library_index)
        except Exception as exc:
            messagebox.showwarning('信息', f'信息已保存，但文件连续重命名失败：{exc}', parent=self)
        self._refresh_workspace()

    def _edit_folder(self, folder: Path):
        if not folder.is_dir():
            return
        pdfs = sorted([p for p in folder.glob('*.pdf') if p.is_file()], key=lambda p: p.name.casefold())
        if not pdfs:
            messagebox.showinfo('编辑', '该文件夹下没有可重新识别的 PDF。', parent=self)
            return
        initial = str(pdfs[0])
        selected = filedialog.askopenfilename(
            parent=self, title='选择主 PDF 重新识别', initialdir=str(folder), initialfile=Path(initial).name,
            filetypes=[('PDF', '*.pdf')],
        )
        if not selected:
            return
        path = Path(selected).resolve()
        try:
            path.relative_to(folder.resolve())
        except ValueError:
            messagebox.showerror('编辑', '请选择该文献文件夹内的 PDF。', parent=self)
            return
        self._open_info(path, auto_on_open=True)

    def _new_note(self, folder: Path):
        if not folder.is_dir():
            return
        notes = folder / 'notes'
        notes.mkdir(parents=True, exist_ok=True)
        for number in range(1, 10000):
            note = notes / f'note{number:02d}.md'
            if not note.exists():
                note.write_text('# 笔记\n\n', encoding='utf-8')
                self._refresh_workspace()
                self._markdown_server().open_edit(note)
                return
        raise RuntimeError('notes/ 中没有可用的 noteXX.md 文件名')

    def _rename_selected(self, _event=None):
        path = self._selected
        if path and path.exists():
            try:
                self._rename(path)
            except Exception as exc:
                messagebox.showerror('重命名', str(exc), parent=self)
        return 'break'

    def _batch_organize(self, paths: list[Path], progress_cb=None):
        if not self.workspace or not self.library_index:
            return
        root = self.workspace.root

        def worker():
            from concurrent.futures import ThreadPoolExecutor
            fetcher = MetadataFetcher(cache_dir=ProjectPaths.for_root(root).metadata_cache)
            index = LibraryIndex(root)
            total = len(paths)
            state = {'done': 0, 'ok': 0, 'errors': []}
            
            
            
            lock = threading.Lock()

            def handle(path):
                message = None
                try:
                    result = fetcher.fetch(path, allow_local_parse=False)
                    if not result.entry or not result.entry.title or result.source == 'local':
                        message = f'{path.name}: 常规数据库未命中，请逐篇点击“信息”后使用 AI复核'
                    else:
                        with lock:
                            if result.supplement.is_supplement:
                                archive_supplement(
                                    root, path, result.entry, index=index,
                                    parent_doi=result.supplement.parent_doi,
                                    supplement_doi=result.doi,
                                )
                            else:
                                duplicate, _reason, _score = index.find_duplicate(result.entry)
                                if duplicate and duplicate.files.get('pdf'):
                                    message = f'{path.name}: 母文章主 PDF 已存在，已跳过'
                                else:
                                    archive_pdf(root, path, result.entry, index=index)
                except Exception as exc:
                    message = f'{path.name}: {exc}'
                with lock:
                    state['done'] += 1
                    if message is None:
                        state['ok'] += 1
                    else:
                        state['errors'].append(message)
                    done = state['done']
                if progress_cb:
                    progress_cb(done, total, path.name)

            workers = max(1, min(6, total))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                list(pool.map(handle, paths))
            if progress_cb:
                progress_cb(total, total, '完成')
            self._queue.put(('batch_done', state['ok'], state['errors']))
        threading.Thread(target=worker, daemon=True).start()

    def _batch_summarize(self, paths: list[Path], progress_cb=None):
        if not self.workspace:
            return
        root = self.workspace.root

        def worker():
            
            
            
            
            ok = 0
            errors = []
            total = len(paths)
            for i, path in enumerate(paths, 1):
                try:
                    generate_note(root, path)
                    ok += 1
                except Exception as exc:
                    errors.append(f'{path.name}: {exc}')
                if progress_cb:
                    progress_cb(i, total, path.name)
            if progress_cb:
                progress_cb(total, total, '完成')
            self._queue.put(('batch_note_done', ok, errors))
        threading.Thread(target=worker, daemon=True).start()

    def _open_batch(self):
        if self.workspace:
            BatchDialog(
                self,
                self.workspace.root,
                self._batch_organize,
                on_summarize=self._batch_summarize,
                on_done=self._refresh_workspace,
            )

    def _start_ai_note(self, path: Path):
        if not self.workspace:
            return
        root = self.workspace.root

        def worker():
            try:
                note = generate_note(root, path)
                self._queue.put(('note_done', note))
            except Exception as exc:
                self._queue.put(('error', 'AI 总结', str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def _start_md_export(self, path: Path):

        def worker():
            try:
                output = md_to_pdf(path)
                self._queue.put(('export_done', output))
            except Exception as exc:
                self._queue.put(('error', 'Markdown 导出', str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def _rename(self, path: Path):
        if not self.library_index:
            return
        new_name = simpledialog.askstring('重命名', '新名称', initialvalue=path.name, parent=self)
        if not new_name or new_name == path.name:
            return
        if any(sep in new_name for sep in ('/', '\\')) or new_name in {'.', '..'}:
            raise ValueError('新名称不能包含路径分隔符。')
        target = path.with_name(new_name)
        if target.exists():
            raise FileExistsError(str(target))
        was_dir = path.is_dir()
        entry = self.library_index.entry_for_path(path) if not was_dir else None
        old_rel = path.relative_to(self.library_index.root).as_posix()
        path.rename(target)
        new_rel = target.relative_to(self.library_index.root).as_posix()
        if was_dir:
            self.library_index.remap_folder_prefix(old_rel, new_rel)
        elif entry:
            for key, value in list(entry.files.items()):
                if isinstance(value, str) and Path(value).name == path.name:
                    entry.files[key] = target.name
                elif isinstance(value, list):
                    entry.files[key] = [target.name if Path(str(item)).name == path.name else item for item in value]
            for attachment in entry.attachments:
                if Path(attachment.path).name == path.name:
                    attachment.path = target.name
            mapping = self.library_index.data.get('mappings', {}).pop(old_rel, None)
            if mapping:
                self.library_index.data.setdefault('mappings', {})[new_rel] = mapping
            self.library_index.upsert(entry)
            if entry.folder:
                write_citation_bundle(self.library_index.root / entry.folder, entry)
        self._refresh_workspace()

    def _delete(self, path: Path):
        if not messagebox.askyesno('删除', f'确定删除？\n{path}', parent=self):
            return
        was_dir = path.is_dir()
        entry = self.library_index.entry_for_path(path) if self.library_index and not was_dir else None
        rel = path.relative_to(self.library_index.root).as_posix() if self.library_index else ''
        if was_dir:
            shutil.rmtree(path)
            if self.library_index:
                self.library_index.remove_folder_prefix(rel)
        else:
            path.unlink()
            if entry and self.library_index:
                mapping = self.library_index.data.get('mappings', {}).pop(rel, None)
                is_primary = path.name == str(entry.files.get('pdf') or '')
                if is_primary:
                    entry.files.pop('pdf', None)
                    entry.attachments = [a for a in entry.attachments if not (a.role == 'primary' or Path(a.path).name == path.name)]
                else:
                    entry.attachments = [a for a in entry.attachments if Path(a.path).name != path.name]
                    entry.files['supplements'] = [a.path for a in entry.supplementary_attachments if a.path]
                if is_primary and not entry.supplementary_attachments:
                    self.library_index.remove(entry.id)
                else:
                    self.library_index.upsert(entry)
                    if entry.folder:
                        write_citation_bundle(self.library_index.root / entry.folder, entry)
        self._refresh_workspace()

    def _poll(self):
        try:
            while True:
                item = self._queue.get_nowait()
                kind = item[0]
                if kind == 'batch_done':
                    ok, errors = item[1], item[2]
                    self._refresh_workspace()
                    detail = '\n'.join(errors[:12])
                    messagebox.showinfo('批量信息识别', f'识别并归档 {ok} 篇，跳过/失败 {len(errors)} 篇。' + (f'\n\n{detail}' if detail else ''), parent=self)
                elif kind == 'note_done':
                    self._refresh_workspace()
                    messagebox.showinfo('AI 总结', f'已生成：\n{item[1]}', parent=self)
                elif kind == 'batch_note_done':
                    ok, errors = item[1], item[2]
                    self._refresh_workspace()
                    detail = '\n'.join(errors[:12])
                    messagebox.showinfo('批量 AI 总结', f'成功 {ok} 篇，失败 {len(errors)} 篇。' + (f'\n\n{detail}' if detail else ''), parent=self)
                elif kind == 'export_done':
                    self._refresh_workspace()
                    messagebox.showinfo('Markdown 导出', f'已生成：\n{item[1]}', parent=self)
                elif kind == 'error':
                    self._refresh_workspace()
                    messagebox.showerror(item[1], item[2], parent=self)
        except queue.Empty:
            pass
        self.after(120, self._poll)

    def destroy(self):
        if self.md_server:
            self.md_server.stop()
        super().destroy()



def extract_doi_safe(text: str) -> str:
    from src.library.fetch import extract_doi
    return extract_doi(text)


def main():
    app = MainWindow()
    app.mainloop()


if __name__ == '__main__':
    main()
