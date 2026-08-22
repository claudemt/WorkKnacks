import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..ai import polish as ai


class PolishDialog(tk.Toplevel):
    def __init__(
        self,
        parent,
        file_path=None,
        category='transcribe',
        project_root=None,
        on_saved=None,
    ):
        super().__init__(parent)
        self.title('AI 润色')
        self.geometry(f'{self.winfo_screenwidth()}x{self.winfo_screenheight()}+0+0')
        self.resizable(True, True)
        self.transient(parent)
        self.file_path = file_path
        self.category = category
        self.project_root = project_root
        self.on_saved = on_saved
        self.round = 0
        self.last_result = ''
        self._queue = queue.Queue()

        ok, msg = ai.detect_claude()
        status_frame = ttk.Frame(self, padding=(12, 10))
        status_frame.pack(fill=tk.X)
        self.claude_label = ttk.Label(
            status_frame, text=('✓ ' if ok else '✗ ') + msg,
            foreground='#2e8b57' if ok else '#b22222')
        self.claude_label.pack(side=tk.LEFT)
        ttk.Button(status_frame, text='选择文件',
                   command=self._pick_file).pack(side=tk.RIGHT)

        file_frame = ttk.Frame(self, padding=(12, 0))
        file_frame.pack(fill=tk.X)
        self.file_label = ttk.Label(file_frame, text=file_path or '未选择文件',
                                    foreground='#444444')
        self.file_label.pack(anchor=tk.W)

        prompt_frame = ttk.LabelFrame(self, text='提示词', padding=8)
        prompt_frame.pack(fill=tk.X, padx=12, pady=(8, 0))
        self.feedback = tk.Text(prompt_frame, height=4, wrap=tk.WORD,
                                font=('Microsoft YaHei UI', 10))
        f_scroll = ttk.Scrollbar(prompt_frame, orient=tk.VERTICAL,
                                 command=self.feedback.yview)
        self.feedback.configure(yscrollcommand=f_scroll.set)
        self.feedback.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        f_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        btn_row = ttk.Frame(self, padding=(12, 8))
        btn_row.pack(fill=tk.X)
        self.polish_btn = ttk.Button(btn_row, text='AI 润色',
                                     command=self._polish)
        self.polish_btn.pack(side=tk.LEFT)
        ttk.Button(btn_row, text='保存到文件',
                   command=self._save).pack(side=tk.LEFT, padx=8)
        ttk.Button(btn_row, text='关闭',
                   command=self.destroy).pack(side=tk.RIGHT)
        self.round_label = ttk.Label(btn_row, text='')
        self.round_label.pack(side=tk.RIGHT, padx=8)

        output_frame = ttk.LabelFrame(self, text='AI 输出', padding=8)
        output_frame.pack(fill=tk.X, padx=12, pady=(0, 12))
        self.preview = tk.Text(output_frame, height=8, wrap=tk.WORD,
                               font=('Microsoft YaHei UI', 10))
        p_scroll = ttk.Scrollbar(output_frame, orient=tk.VERTICAL,
                                 command=self.preview.yview)
        self.preview.configure(yscrollcommand=p_scroll.set)
        self.preview.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        p_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.after(100, self._poll)

    def _pick_file(self):
        path = filedialog.askopenfilename(
            title='选择要润色的文件',
            filetypes=[('文本', '*.md *.txt *.tex *.srt *.vtt'), ('全部', '*.*')])
        if path:
            self.file_path = path
            self.file_label.configure(text=path)
            self.round = 0
            self.last_result = ''
            self.preview.delete('1.0', tk.END)

    def _polish(self):
        if not self.file_path or not os.path.exists(self.file_path):
            messagebox.showwarning('AI 润色', '请先选择文件', parent=self)
            return
        ok, msg = ai.detect_claude()
        if not ok:
            messagebox.showerror('AI 润色', msg, parent=self)
            return

        prompt = self.feedback.get('1.0', 'end').strip()
        self.round += 1
        self.polish_btn.configure(state=tk.DISABLED)
        self.round_label.configure(text=f'润色中 · 第{self.round}轮 ...')

        def work():
            try:
                output = ai.polish(
                    self.file_path,
                    feedback=prompt or None,
                    history_path=str(ai.log_path_for(
                        self.file_path, self.project_root)),
                    category=self.category,
                )
                ai.append_log(
                    self.file_path,
                    self.round,
                    prompt or None,
                    output,
                    self.project_root,
                )
                self.last_result = output
                self._queue.put(('done', self.round, output))
            except Exception as e:
                self._queue.put(('error', str(e)))
        threading.Thread(target=work, daemon=True).start()

    def _poll(self):
        try:
            while True:
                item = self._queue.get_nowait()
                if item[0] == 'done':
                    _, round_no, output = item
                    self.preview.insert(tk.END,
                                        f'\n\n=== 第{round_no}轮 ===\n\n{output}\n')
                    self.preview.see(tk.END)
                    self.round_label.configure(text=f'完成 · 第{round_no}轮')
                    self.polish_btn.configure(state=tk.NORMAL)
                else:
                    self.round_label.configure(text='失败')
                    self.polish_btn.configure(state=tk.NORMAL)
                    messagebox.showerror('AI 润色', item[1], parent=self)
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _save(self):
        if not self.file_path:
            messagebox.showwarning('AI 润色', '请先选择文件', parent=self)
            return
        if not self.last_result.strip():
            messagebox.showwarning('AI 润色', '还没有润色结果', parent=self)
            return
        with open(self.file_path, 'w', encoding='utf-8') as f:
            f.write(self.last_result + '\n')
        if self.on_saved:
            self.on_saved(self.file_path)
        messagebox.showinfo('AI 润色',
                            f'已覆盖保存 {self.file_path}\n'
                            f'工作记录: {ai.log_dir_for(self.file_path, self.project_root)}',
                            parent=self)


def open_polish(
    parent,
    file_path=None,
    category='transcribe',
    project_root=None,
    on_saved=None,
):
    return PolishDialog(
        parent,
        file_path,
        category,
        project_root=project_root,
        on_saved=on_saved,
    )
