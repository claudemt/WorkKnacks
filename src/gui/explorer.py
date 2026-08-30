from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk

from src.core.workspace import ProjectWorkspace
from src.library.index import LibraryIndex


PDF_ACTIONS = [('view', '查看'), ('info', '信息'), ('translate', '翻译'), ('parse', '解析'), ('ai', 'AI')]
MD_ACTIONS = [('view', '查看'), ('md_edit', '编辑'), ('ai', 'AI')]
TXT_ACTIONS = [('view', '查看'), ('translate', '翻译'), ('ai', 'AI')]
MEDIA_EXTS = {'.mp3', '.wav', '.m4a', '.mp4', '.mkv', '.mov'}


def bind_recursive(widget, event, handler):
    widget.bind(event, handler)
    for child in widget.winfo_children():
        bind_recursive(child, event, handler)


class ExplorerView(ttk.Frame):
    def __init__(self, parent, on_action, on_select=None):
        super().__init__(parent)
        self.on_action = on_action
        self.on_select = on_select
        self.workspace: ProjectWorkspace | None = None
        self.index: LibraryIndex | None = None
        self.selected_path: Path | None = None
        self._rows: dict[Path, FileRow] = {}
        self.canvas = tk.Canvas(self, highlightthickness=0, background='#f7f7f7')
        self.scrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self.window_id = self.canvas.create_window((0, 0), window=self.inner, anchor='nw')
        self.inner.bind('<Configure>', lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfigure(self.window_id, width=e.width))
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def render(self, workspace: ProjectWorkspace, folders: list[Path], docs: list[Path], index: LibraryIndex | None = None):
        previous = self.selected_path
        self.workspace = workspace
        self.index = index
        self.selected_path = None
        self._rows.clear()
        for child in self.inner.winfo_children():
            child.destroy()
        managed_folders = set()
        if index is not None:
            for entry in index.entries():
                if entry.folder:
                    managed_folders.add((index.root / entry.folder).resolve())
        for path in folders:
            row = FileRow(self.inner, path, True, workspace, self._select, self.on_action, managed_dir=path.resolve() in managed_folders)
            row.pack(fill=tk.X, pady=2)
            self._rows[path] = row
        for path in docs:
            row = FileRow(self.inner, path, False, workspace, self._select, self.on_action, managed_dir=False)
            row.pack(fill=tk.X, pady=2)
            self._rows[path] = row
        if not folders and not docs:
            ttk.Label(self.inner, text='当前目录为空', padding=20).pack(anchor=tk.W)
        if previous in self._rows:
            self._select(previous)
        self.canvas.yview_moveto(0)

    def _select(self, path: Path):
        self.selected_path = path
        for candidate, row in self._rows.items():
            row.set_selected(candidate == path)
        if self.on_select:
            self.on_select(path)


class FileRow(ttk.Frame):


    def __init__(self, parent, path: Path, is_dir: bool, workspace: ProjectWorkspace, on_select, on_action, managed_dir: bool = False):
        super().__init__(parent, padding=(8, 8), relief=tk.GROOVE, borderwidth=1)
        self.path = path
        self.is_dir = is_dir
        self.workspace = workspace
        self.on_select = on_select
        self.on_action = on_action
        self.managed_dir = managed_dir
        self.columnconfigure(0, weight=1, minsize=160)

        icon = '📁' if is_dir else _icon(path)
        self.name_label = ttk.Label(
            self,
            text=f'{icon} {path.name}',
            font=('Microsoft YaHei UI', 10, 'bold'),
            anchor=tk.W,
            justify=tk.LEFT,
            width=1,
        )
        self.name_label.grid(row=0, column=0, sticky=tk.EW)

        actions = ttk.Frame(self)
        actions.grid(row=0, column=1, sticky=tk.E)
        action_items = ([('enter', '进入'), ('folder_edit', '编辑'), ('new_note', '笔记')] if managed_dir else [('enter', '进入')]) if is_dir else _actions_for(path)
        for action, label in action_items:
            ttk.Button(actions, text=label, width=max(5, len(label) + 1), command=lambda a=action: on_action(a, path)).pack(side=tk.LEFT, padx=1)

        self.bind('<Configure>', self._resize_name, add='+')
        self.bind('<Button-1>', lambda _e: on_select(path), add='+')
        bind_recursive(self.name_label, '<Button-1>', lambda _e: on_select(path))
        bind_recursive(self.name_label, '<Double-Button-1>', lambda _e: on_action('enter' if is_dir else 'view', path))
        bind_recursive(self.name_label, '<Button-3>', self._context_menu)

    def set_selected(self, selected: bool) -> None:

        self.configure(relief=tk.SUNKEN if selected else tk.GROOVE)

    def _resize_name(self, event=None):
        width = event.width if event is not None else self.winfo_width()
        children = self.winfo_children()
        action_width = children[-1].winfo_reqwidth() if len(children) > 1 else 0
        self.name_label.configure(wraplength=max(120, width - action_width - 34))

    def _context_menu(self, event):
        self.on_select(self.path)
        menu = tk.Menu(self, tearoff=0)
        if self.is_dir:
            menu.add_command(label='进入', command=lambda: self.on_action('enter', self.path))
            if self.managed_dir:
                menu.add_command(label='编辑/重新识别', command=lambda: self.on_action('folder_edit', self.path))
                menu.add_command(label='新建笔记', command=lambda: self.on_action('new_note', self.path))
        else:
            menu.add_command(label='查看', command=lambda: self.on_action('view', self.path))
            menu.add_command(label='发送给 AI', command=lambda: self.on_action('send_ai', self.path))
            suffix = self.path.suffix.lower()
            if suffix == '.pdf':
                menu.add_command(label='生成论文总结', command=lambda: self.on_action('summarize', self.path))
            if suffix in {'.md', '.markdown'}:
                menu.add_command(label='导出 PDF', command=lambda: self.on_action('md_export', self.path))
            if suffix in {'.md', '.markdown', '.txt', '.tex'}:
                menu.add_command(label='润色', command=lambda: self.on_action('polish', self.path))
        menu.add_separator()
        menu.add_command(label='重命名  F2', command=lambda: self.on_action('rename', self.path))
        menu.add_command(label='复制路径  Shift+Alt+C', command=lambda: self.on_action('copy_path', self.path))
        menu.add_command(label='在资源管理器中显示  Shift+Alt+R', command=lambda: self.on_action('reveal', self.path))
        menu.add_separator()
        menu.add_command(label='删除  Del', command=lambda: self.on_action('delete', self.path))
        menu.tk_popup(event.x_root, event.y_root)


def _actions_for(path: Path):
    suffix = path.suffix.lower()
    if suffix == '.pdf':
        return PDF_ACTIONS
    if suffix in {'.md', '.markdown'}:
        return MD_ACTIONS
    if suffix in {'.txt', '.tex', '.srt', '.vtt', '.csv', '.json'}:
        return TXT_ACTIONS
    if suffix in MEDIA_EXTS:
        return [('view', '查看'), ('ai', 'AI')]


def _icon(path: Path) -> str:
    return {'.pdf': '📕', '.md': '📝', '.markdown': '📝', '.txt': '📄', '.tex': '📄'}.get(path.suffix.lower(), '📄')
