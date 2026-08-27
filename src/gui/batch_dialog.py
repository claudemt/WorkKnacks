from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from src.library.biblio import export_bibtex
from src.library.index import LibraryIndex
from src.library.scan import scan_project
from .layout import fit_window
from .widgets import ProgressBar


class BatchDialog(tk.Toplevel):
    

    def __init__(self, parent, root: str | Path, on_organize, on_summarize=None, on_done=None):
        super().__init__(parent)
        self.title('批量')
        fit_window(self, 720, 540, min_width=580, min_height=420)
        self.transient(parent)
        self.root_path = Path(root).resolve()
        self.on_organize = on_organize
        self.on_summarize = on_summarize
        self.on_done = on_done
        self.index = LibraryIndex(self.root_path)

        body = ttk.Frame(self, padding=14)
        body.pack(fill=tk.BOTH, expand=True)
        top = ttk.Frame(body)
        top.pack(fill=tk.X)
        ttk.Label(top, text='PDF', font=('Microsoft YaHei UI', 11, 'bold')).pack(side=tk.LEFT)
        self.select_all_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text='全选', variable=self.select_all_var, command=self._toggle_all).pack(side=tk.RIGHT)

        self.listbox = tk.Listbox(body, width=1, selectmode=tk.EXTENDED, exportselection=False)
        self.listbox.pack(fill=tk.BOTH, expand=True, pady=(8, 10))
        self.listbox.bind('<<ListboxSelect>>', self._selection_changed)
        self._refresh()

        actions = ttk.Frame(body)
        actions.pack(fill=tk.X)
        ttk.Button(actions, text='信息', command=self._organize).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(actions, text='总结', command=self._summarize).pack(side=tk.LEFT, padx=6)
        ttk.Button(actions, text='导出', command=self._export).pack(side=tk.LEFT, padx=6)
        ttk.Button(actions, text='关闭', command=self.destroy).pack(side=tk.RIGHT)

        self.progress = ProgressBar(body)
        self.progress.pack(fill=tk.X, pady=(10, 0))
        
        
        self._progress_cb = lambda done, total, message: self.progress.set(done, total, message)

    def _refresh(self):
        scan = scan_project(self.root_path, self.index.reload())
        seen: set[Path] = set()
        paths: list[Path] = []
        for path in [*scan.raw, *scan.organized]:
            path = path.resolve()
            if path in seen or self._is_generated_pdf(path):
                continue
            seen.add(path)
            paths.append(path)
        
        for entry in self.index.entries():
            for attachment in entry.attachments:
                if not attachment.path or not entry.folder:
                    continue
                path = (self.root_path / entry.folder / attachment.path).resolve()
                if path.is_file() and path.suffix.lower() == '.pdf' and path not in seen:
                    seen.add(path); paths.append(path)
        self.paths = sorted(paths, key=lambda p: p.relative_to(self.root_path).as_posix().casefold())
        self.listbox.delete(0, tk.END)
        for path in self.paths:
            self.listbox.insert(tk.END, path.relative_to(self.root_path).as_posix())
        self.select_all_var.set(False)

    def _is_generated_pdf(self, path: Path) -> bool:
        try:
            rel = path.relative_to(self.root_path)
        except ValueError:
            return True
        return 'parsed' in rel.parts or 'translations' in rel.parts or 'notes' in rel.parts

    def _toggle_all(self):
        if self.select_all_var.get():
            self.listbox.selection_set(0, tk.END)
        else:
            self.listbox.selection_clear(0, tk.END)

    def _selection_changed(self, _event=None):
        count = len(self.listbox.curselection())
        self.select_all_var.set(bool(self.paths) and count == len(self.paths))

    def _selected_paths(self) -> list[Path]:
        return [self.paths[i] for i in self.listbox.curselection()]

    def _organize(self):
        paths = self._selected_paths()
        if not paths:
            messagebox.showinfo('批量信息', '请先选择 PDF。', parent=self)
            return
        self.progress.reset()
        self.on_organize(paths, self._progress_cb)
        self.after(250, self._refresh)

    def _summarize(self):
        if not self.on_summarize:
            return
        paths = [path for path in self._selected_paths() if self.index.entry_for_path(path)]
        if not paths:
            messagebox.showinfo('批量总结', '请选择已经识别的 PDF。', parent=self)
            return
        if messagebox.askyesno('批量总结', f'将依次总结 {len(paths)} 个 PDF，继续吗？', parent=self):
            self.progress.reset()
            self.on_summarize(paths, self._progress_cb)

    def _export(self):
        selected = self._selected_paths()
        entries = []
        seen = set()
        for path in selected:
            entry = self.index.entry_for_path(path)
            if entry and entry.id not in seen:
                seen.add(entry.id); entries.append(entry)
        if not entries:
            messagebox.showinfo('导出 BibTeX', '请选择已经识别的 PDF。', parent=self)
            return
        path = filedialog.asksaveasfilename(parent=self, defaultextension='.bib', filetypes=[('BibTeX', '*.bib')], initialfile='library.bib')
        if not path:
            return
        export_bibtex(entries, path)
        messagebox.showinfo('导出 BibTeX', f'已导出 {len(entries)} 条记录。', parent=self)
