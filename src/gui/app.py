from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ..core.config import config
from ..core.workspace import ProjectWorkspace
from . import docs_viewer
from .config_dialog import open_config
from .operation_dialog import open_operation
from .skill_dialog import open_skill_picker


ACTION_NAMES = {
    'translate': '翻译',
    'transcribe': '转写',
    'parse': '解析',
    'polish': 'AI 润色',
}
TEXT_EXTENSIONS = {'.md', '.txt', '.tex', '.srt', '.vtt', '.csv', '.json'}
PARSE_EXTENSIONS = {
    '.pdf', '.doc', '.docx', '.ppt', '.pptx', '.png', '.jpg', '.jpeg',
}


def bind_recursive(widget, event, handler):
    """让双击事件穿透子控件（tkinter 事件不会自动向父级冒泡）。"""

    widget.bind(event, handler)
    for child in widget.winfo_children():
        bind_recursive(child, event, handler)


class FolderRow(ttk.Frame):
    def __init__(self, parent, workspace, path, rel_path, on_open):
        super().__init__(parent, padding=(8, 7))
        self.configure(relief=tk.GROOVE, borderwidth=1)
        self.columnconfigure(0, weight=1)

        info = ttk.Frame(self)
        info.grid(row=0, column=0, sticky=tk.EW)
        info.columnconfigure(0, weight=1)
        ttk.Label(
            info,
            text='📁 ' + path.name,
            font=('Microsoft YaHei UI', 10, 'bold'),
        ).grid(row=0, column=0, sticky=tk.W)
        ttk.Label(
            info,
            text=rel_path,
            foreground='#666666',
        ).grid(row=1, column=0, sticky=tk.W, pady=(2, 0))

        ttk.Label(
            self,
            text='文件夹',
            foreground='#555555',
        ).grid(row=0, column=1, padx=12)
        ttk.Label(
            self,
            text='双击进入',
            foreground='#888888',
        ).grid(row=0, column=2, padx=12)
        bind_recursive(self, '<Double-Button-1>', lambda _: on_open(path))


class DocumentRow(ttk.Frame):
    def __init__(self, parent, workspace, path, on_action, on_open=None):
        super().__init__(parent, padding=(8, 7))
        self.workspace = workspace
        self.path = path
        self.on_action = on_action
        self.configure(relief=tk.GROOVE, borderwidth=1)
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, minsize=78)
        self.columnconfigure(2, minsize=285)

        info = ttk.Frame(self)
        info.grid(row=0, column=0, sticky=tk.EW)
        info.columnconfigure(0, weight=1)
        ttk.Label(
            info,
            text=path.name,
            font=('Microsoft YaHei UI', 10, 'bold'),
        ).grid(row=0, column=0, sticky=tk.W)
        ttk.Label(
            info,
            text=workspace.relative_path(path),
            foreground='#666666',
        ).grid(row=1, column=0, sticky=tk.W, pady=(2, 0))

        ttk.Label(
            self,
            text=path.suffix.lower().lstrip('.').upper() or '文件',
            foreground='#555555',
        ).grid(row=0, column=1, padx=12)

        status_frame = ttk.Frame(self)
        status_frame.grid(row=0, column=2, sticky=tk.EW, padx=(0, 12))
        self.status_labels = {}
        for index, category in enumerate(('translate', 'transcribe', 'parse')):
            label = ttk.Label(status_frame, text='')
            label.grid(row=0, column=index, padx=3)
            self.status_labels[category] = label
        self.refresh_status()

        action_frame = ttk.Frame(self)
        action_frame.grid(row=0, column=3, sticky=tk.E)
        self.action_buttons = {}
        for category in ('translate', 'transcribe', 'parse', 'polish'):
            button = ttk.Button(
                action_frame,
                text=ACTION_NAMES[category],
                width=8 if category != 'polish' else 10,
                command=lambda selected=category: self.on_action(
                    selected, self.path
                ),
            )
            button.pack(side=tk.LEFT, padx=2)
            self.action_buttons[category] = button
        self._refresh_capabilities()
        if on_open:
            bind_recursive(self, '<Double-Button-1>',
                           lambda _: on_open(self.path))

    def _refresh_capabilities(self):
        suffix = self.path.suffix.lower()
        self.action_buttons['translate'].configure(
            state=tk.NORMAL if suffix in TEXT_EXTENSIONS else tk.DISABLED
        )
        self.action_buttons['parse'].configure(
            state=tk.NORMAL if suffix in PARSE_EXTENSIONS else tk.DISABLED
        )
        self.action_buttons['polish'].configure(
            state=tk.NORMAL if suffix in TEXT_EXTENSIONS else tk.DISABLED
        )

    def refresh_status(self):
        for category, label in self.status_labels.items():
            status = self.workspace.category_status(self.path, category)
            label.configure(
                text=f'{ACTION_NAMES[category]}: {status}',
                foreground={
                    '已完成': '#2e8b57',
                    '处理中': '#996515',
                    '失败': '#b22222',
                }.get(status, '#777777'),
            )


class DocumentList(ttk.Frame):
    def __init__(self, parent, on_action):
        super().__init__(parent)
        self.on_action = on_action
        self.on_open_folder = None
        self.on_open_file = None
        self.canvas = tk.Canvas(
            self,
            highlightthickness=0,
            background='#f5f6f8',
        )
        self.scrollbar = ttk.Scrollbar(
            self,
            orient=tk.VERTICAL,
            command=self.canvas.yview,
        )
        self.inner = ttk.Frame(self.canvas)
        self.inner.bind(
            '<Configure>',
            lambda _: self.canvas.configure(
                scrollregion=self.canvas.bbox('all')
            ),
        )
        self.window_id = self.canvas.create_window(
            (0, 0),
            window=self.inner,
            anchor='nw',
        )
        self.canvas.bind(
            '<Configure>',
            lambda event: self.canvas.itemconfigure(
                self.window_id,
                width=event.width,
            ),
        )
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def clear(self):
        for child in self.inner.winfo_children():
            child.destroy()

    def render(self, workspace: ProjectWorkspace,
               folders: list, docs: list):
        self.clear()
        for path in folders:
            FolderRow(
                self.inner,
                workspace,
                path,
                workspace.relative_path(path),
                self.on_open_folder or (lambda _p: None),
            ).pack(fill=tk.X, pady=3)
        for path in docs:
            DocumentRow(
                self.inner,
                workspace,
                path,
                self.on_action,
                on_open=self.on_open_file,
            ).pack(fill=tk.X, pady=3)
        self.canvas.yview_moveto(0)


class MainWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('WorkKnacks · 项目文档工具')
        self.geometry('1320x820')
        self.minsize(1040, 680)
        self.workspace = None
        self.current_rel = ''

        self._build_layout()
        remembered = config.get('LAST_PROJECT')
        if remembered and Path(remembered).is_dir():
            self._set_workspace(remembered)
        else:
            self._show_empty()

    def _build_layout(self):
        header = ttk.Frame(self, padding=(18, 14, 18, 10))
        header.pack(fill=tk.X)
        ttk.Label(
            header,
            text='WorkKnacks',
            font=('Segoe UI', 18, 'bold'),
        ).pack(side=tk.LEFT)
        ttk.Label(
            header,
            text='项目文档处理工具',
            foreground='#666666',
        ).pack(side=tk.LEFT, padx=12, pady=(5, 0))

        commands = ttk.Frame(header)
        commands.pack(side=tk.RIGHT)
        ttk.Button(
            commands,
            text='打开项目文件夹',
            command=self._open_project,
        ).pack(side=tk.LEFT, padx=3)
        ttk.Button(
            commands,
            text='刷新',
            command=self._refresh_workspace,
        ).pack(side=tk.LEFT, padx=3)
        ttk.Button(
            commands,
            text='配置',
            command=self._open_config,
        ).pack(side=tk.LEFT, padx=3)
        ttk.Button(
            commands,
            text='帮助',
            command=lambda: docs_viewer.open_docs('index'),
        ).pack(side=tk.LEFT, padx=3)

        ttk.Separator(self).pack(fill=tk.X)

        project_bar = ttk.Frame(self, padding=(18, 12, 18, 8))
        project_bar.pack(fill=tk.X)
        self.project_name = ttk.Label(
            project_bar,
            text='尚未打开项目',
            font=('Microsoft YaHei UI', 13, 'bold'),
        )
        self.project_name.pack(side=tk.LEFT)
        self.project_path = ttk.Label(
            project_bar,
            text='',
            foreground='#666666',
        )
        self.project_path.pack(side=tk.LEFT, padx=12)
        self.project_summary = ttk.Label(
            project_bar,
            text='',
            foreground='#555555',
        )
        self.project_summary.pack(side=tk.RIGHT)
        self.open_folder_button = ttk.Button(
            project_bar,
            text='在资源管理器中打开',
            command=self._open_current_folder,
        )
        self.open_folder_button.pack(side=tk.RIGHT, padx=10)
        self.open_folder_button.configure(state=tk.DISABLED)

        list_header = ttk.Frame(self, padding=(18, 0, 18, 4))
        list_header.pack(fill=tk.X)
        ttk.Label(
            list_header,
            text='项目文档',
            font=('Microsoft YaHei UI', 11, 'bold'),
        ).pack(side=tk.LEFT)
        ttk.Label(
            list_header,
            text='双击文件夹进入 · 双击文件打开 · 处理结果写入源文件所在目录',
            foreground='#777777',
        ).pack(side=tk.LEFT, padx=12)

        nav_bar = ttk.Frame(self, padding=(18, 0, 18, 6))
        nav_bar.pack(fill=tk.X)
        self.back_btn = ttk.Button(
            nav_bar,
            text='⬆ 返回上级',
            command=self._go_up,
            state=tk.DISABLED,
        )
        self.back_btn.pack(side=tk.LEFT)
        self.nav_label = ttk.Label(nav_bar, text='/', foreground='#555555')
        self.nav_label.pack(side=tk.LEFT, padx=10)

        self.empty = ttk.Frame(self, padding=40)
        ttk.Label(
            self.empty,
            text='打开一个项目文件夹',
            font=('Microsoft YaHei UI', 16, 'bold'),
        ).pack(pady=(80, 8))
        ttk.Label(
            self.empty,
            text='项目可以位于电脑上的任意本地目录。',
            foreground='#666666',
        ).pack()

        self.document_list = DocumentList(self, self._handle_action)
        self.document_list.on_open_folder = self._enter_folder
        self.document_list.on_open_file = self._open_file
        self.document_list.pack(
            fill=tk.BOTH,
            expand=True,
            padx=18,
            pady=(0, 14),
        )

    def _show_empty(self):
        self.document_list.pack_forget()
        self.empty.pack(fill=tk.BOTH, expand=True)
        self.project_name.configure(text='尚未打开项目')
        self.project_path.configure(text='')
        self.project_summary.configure(text='')
        self.open_folder_button.configure(state=tk.DISABLED)

    def _set_workspace(self, root):
        try:
            workspace = ProjectWorkspace(root).ensure()
        except Exception as exc:
            messagebox.showerror('项目文件夹', str(exc), parent=self)
            return
        self.workspace = workspace
        self.current_rel = ''
        config.set('LAST_PROJECT', str(workspace.root))
        self.project_name.configure(
            text=workspace.root.name or str(workspace.root)
        )
        self.project_path.configure(text=str(workspace.root))
        self.open_folder_button.configure(state=tk.NORMAL)
        self.empty.pack_forget()
        self.document_list.pack(
            fill=tk.BOTH,
            expand=True,
            padx=18,
            pady=(0, 14),
        )
        self._refresh_workspace()

    def _open_project(self):
        selected = filedialog.askdirectory(
            title='选择项目文件夹',
            mustexist=True,
        )
        if selected:
            self._set_workspace(selected)

    def _refresh_workspace(self):
        if not self.workspace:
            self._show_empty()
            return
        self.workspace.state = self.workspace._load_state()
        folders, docs = self.workspace.list_dir(self.current_rel)
        self.document_list.render(self.workspace, folders, docs)
        self.back_btn.configure(
            state=tk.NORMAL if self.current_rel else tk.DISABLED
        )
        self.nav_label.configure(
            text='/' + self.current_rel if self.current_rel else '/'
        )
        summary = self.workspace.summarize()
        self.project_summary.configure(
            text=(
                f'文档 {summary["documents"]} · '
                f'已处理 {summary["processed"]} · '
                f'失败 {summary["errors"]}'
            )
        )

    def _enter_folder(self, folder_path):
        self.current_rel = self.workspace.relative_path(folder_path)
        self._refresh_workspace()

    def _go_up(self):
        if not self.current_rel:
            return
        parts = self.current_rel.split('/')
        self.current_rel = '/'.join(parts[:-1])
        self._refresh_workspace()

    def _open_file(self, path):
        if path.exists():
            os.startfile(str(path))

    def _handle_action(self, category, path):
        if not self.workspace:
            return
        if category == 'polish':
            open_skill_picker(
                self,
                str(path),
                str(self.workspace.root),
                on_saved=self._refresh_workspace,
            )
            return
        open_operation(
            self,
            self.workspace,
            str(path),
            category,
            on_done=self._refresh_workspace,
        )

    def _open_current_folder(self):
        if self.workspace and self.workspace.root.exists():
            os.startfile(str(self.workspace.root))

    def _open_config(self):
        open_config(self, on_saved=self._refresh_workspace)


def main():
    app = MainWindow()
    app.mainloop()


if __name__ == '__main__':
    main()
