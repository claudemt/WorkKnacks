import tkinter as tk
from tkinter import ttk

from .polish_dialog import open_polish


SKILLS = [
    ('translate', '翻译稿润色', '适合翻译结果、双语材料和术语一致性检查'),
    ('transcribe', '转写稿整理', '适合会议纪要、逐字稿和口语内容整理'),
    ('parse', '解析稿校对', '适合 PDF/图片解析后的 Markdown 清理'),
]


class SkillDialog(tk.Toplevel):
    def __init__(self, parent, file_path, project_root, on_saved=None):
        super().__init__(parent)
        self.title('选择 AI Skill')
        self.geometry('460x240')
        self.resizable(False, False)
        self.transient(parent)
        self.file_path = file_path
        self.project_root = project_root
        self.on_saved = on_saved

        body = ttk.Frame(self, padding=16)
        body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(body, text='选择本轮对话使用的处理规范').pack(anchor=tk.W)

        self.skill_var = tk.StringVar(value=SKILLS[0][1])
        self.skill_combo = ttk.Combobox(
            body,
            textvariable=self.skill_var,
            state='readonly',
            values=[label for _, label, _ in SKILLS],
        )
        self.skill_combo.pack(fill=tk.X, pady=(10, 4))
        self.description = ttk.Label(body, text='', foreground='#666666')
        self.description.pack(anchor=tk.W)
        self.skill_combo.bind('<<ComboboxSelected>>', self._refresh_description)
        self._refresh_description()

        row = ttk.Frame(body)
        row.pack(fill=tk.X, pady=(22, 0))
        ttk.Button(row, text='开始 AI 润色', command=self._open).pack(
            side=tk.RIGHT
        )
        ttk.Button(row, text='取消', command=self.destroy).pack(
            side=tk.RIGHT,
            padx=8,
        )

    def _selected_skill(self):
        index = self.skill_combo.current()
        return SKILLS[index] if 0 <= index < len(SKILLS) else SKILLS[0]

    def _refresh_description(self, *_):
        self.description.configure(text=self._selected_skill()[2])

    def _open(self):
        category = self._selected_skill()[0]
        self.destroy()
        open_polish(
            self.master,
            self.file_path,
            category,
            project_root=self.project_root,
            on_saved=self.on_saved,
        )


def open_skill_picker(parent, file_path, project_root, on_saved=None):
    return SkillDialog(
        parent,
        file_path,
        project_root,
        on_saved=on_saved,
    )
