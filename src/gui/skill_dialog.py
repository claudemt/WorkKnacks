from __future__ import annotations

import shutil
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from src.agent.skills import _frontmatter, _valid_skill_name, project_skills_dir
from .layout import fit_window


class ProjectSkillDialog(tk.Toplevel):


    def __init__(self, parent, root: str | Path):
        super().__init__(parent)
        self.title('项目 Skill')
        fit_window(self, 780, 620, min_width=600, min_height=460)
        self.transient(parent)
        self.skill_root = project_skills_dir(root)
        self.skill_root.mkdir(parents=True, exist_ok=True)

        body = ttk.Frame(self, padding=12)
        body.pack(fill=tk.BOTH, expand=True)
        body.columnconfigure(0, weight=0)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        side = ttk.Frame(body)
        side.grid(row=0, column=0, sticky=tk.NS, padx=(0, 10))
        ttk.Label(side, text='已有 Skill', font=('Microsoft YaHei UI', 10, 'bold')).pack(anchor=tk.W)
        self.listbox = tk.Listbox(side, width=22, height=18)
        self.listbox.pack(fill=tk.Y, pady=(6, 6))
        self.listbox.bind('<<ListboxSelect>>', lambda _e: self._load_selected())

        btn_row = ttk.Frame(side)
        btn_row.pack(fill=tk.X)
        ttk.Button(btn_row, text='新建', command=self._new).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 4))
        ttk.Button(btn_row, text='导入', command=self._import).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 4))
        ttk.Button(btn_row, text='删除', command=self._delete).pack(side=tk.LEFT, expand=True, fill=tk.X)

        editor = ttk.Frame(body)
        editor.grid(row=0, column=1, sticky=tk.NSEW)
        editor.rowconfigure(0, weight=1)
        editor.columnconfigure(0, weight=1)
        self.editor = tk.Text(editor, wrap=tk.WORD, font=('Cascadia Code', 10),
                              undo=True, borderwidth=1, relief=tk.SOLID)
        scroll = ttk.Scrollbar(editor, orient=tk.VERTICAL, command=self.editor.yview)
        self.editor.configure(yscrollcommand=scroll.set)
        self.editor.grid(row=0, column=0, sticky=tk.NSEW)
        scroll.grid(row=0, column=1, sticky=tk.NS)

        footer = ttk.Frame(body)
        footer.grid(row=1, column=0, columnspan=2, sticky=tk.EW, pady=(10, 0))
        ttk.Label(footer, text='保存位置：.workknacks/skills/<名称>/SKILL.md',
                  font=('Microsoft YaHei UI', 8), foreground='#888').pack(side=tk.LEFT)
        ttk.Button(footer, text='关闭', command=self.destroy).pack(side=tk.RIGHT)
        ttk.Button(footer, text='保存', command=self._save).pack(side=tk.RIGHT, padx=8)

        self._refresh_list()

    def _names(self) -> list[str]:
        try:
            return sorted(
                (p.name for p in self.skill_root.iterdir()
                 if p.is_dir() and not p.is_symlink() and _valid_skill_name(p.name)),
                key=str.casefold,
            )
        except OSError:
            return []

    def _refresh_list(self, select: str | None = None):
        self.listbox.delete(0, tk.END)
        for name in self._names():
            self.listbox.insert(tk.END, name)
        if select and select in self._names():
            self.listbox.selection_set(self._names().index(select))
            self._load_selected()

    def _dir(self, name: str) -> Path:
        return self.skill_root / name

    def _load_selected(self):
        selection = self.listbox.curselection()
        if not selection:
            return
        name = self.listbox.get(selection[0])
        path = self._dir(name) / 'SKILL.md'
        self.editor.delete('1.0', tk.END)
        if path.is_file():
            self.editor.insert(tk.END, path.read_text(encoding='utf-8', errors='replace'))

    def _new(self):
        name = simpledialog.askstring('新建项目 Skill', 'Skill 名称（字母/数字/._-）', parent=self)
        if not name:
            return
        name = name.strip()
        if not _valid_skill_name(name):
            messagebox.showerror('新建 Skill', f'无效的名称：{name}', parent=self)
            return
        target = self._dir(name)
        if (target / 'SKILL.md').exists():
            messagebox.showwarning('新建 Skill', f'{name} 已存在，将改为编辑它。', parent=self)
        else:
            target.mkdir(parents=True, exist_ok=True)
            (target / 'SKILL.md').write_text(
                f'---\nname: {name}\ndescription: 一句话说明这个 Skill 做什么。\nallowed-tools: Read,Write,Edit,Glob,Grep\n---\n\n# {name}\n\n写清楚：目标、适用场景、必须遵守的规则、输出方式。\n',
                encoding='utf-8',
            )
        self._refresh_list(select=name)
        self.editor.focus_set()

    def _import(self):
        path = filedialog.askopenfilename(
            parent=self,
            title='导入 Skill（.md 文件）',
            filetypes=[('Markdown / SKILL.md', '*.md *.markdown'), ('所有文件', '*.*')],
        )
        if not path:
            return
        source = Path(path)
        try:
            text = source.read_text(encoding='utf-8', errors='replace')
        except OSError as exc:
            messagebox.showerror('导入', f'无法读取文件：{exc}', parent=self)
            return
        name = ''
        try:
            meta, _ = _frontmatter(text)
            name = str(meta.get('name') or '').strip().strip('"\'')
        except Exception:
            pass
        if not _valid_skill_name(name):

            name = source.stem.strip()
        if not _valid_skill_name(name):
            messagebox.showerror('导入', f'无法从文件推导 Skill 名称：{source.name}', parent=self)
            return
        target = self._dir(name)
        if (target / 'SKILL.md').exists():
            if not messagebox.askyesno('导入', f'Skill「{name}」已存在，是否覆盖？', parent=self):
                return
        target.mkdir(parents=True, exist_ok=True)
        (target / 'SKILL.md').write_text(text, encoding='utf-8')
        self._refresh_list(select=name)
        messagebox.showinfo('导入', f'已导入为 .workknacks/skills/{name}/SKILL.md', parent=self)

    def _delete(self):
        selection = self.listbox.curselection()
        if not selection:
            return
        name = self.listbox.get(selection[0])
        if not messagebox.askyesno('删除 Skill', f'确定删除项目 Skill「{name}」吗？', parent=self):
            return
        shutil.rmtree(self._dir(name), ignore_errors=True)
        self.editor.delete('1.0', tk.END)
        self._refresh_list()

    def _save(self):
        selection = self.listbox.curselection()
        if not selection:
            messagebox.showinfo('保存', '请先选择或新建一个 Skill。', parent=self)
            return
        name = self.listbox.get(selection[0])
        target = self._dir(name)
        target.mkdir(parents=True, exist_ok=True)
        content = self.editor.get('1.0', 'end-1c')
        (target / 'SKILL.md').write_text(content, encoding='utf-8')
        messagebox.showinfo('保存', f'已保存 .workknacks/skills/{name}/SKILL.md', parent=self)


def open_project_skills(parent, root: str | Path):
    return ProjectSkillDialog(parent, root)
