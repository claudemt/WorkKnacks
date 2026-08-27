from __future__ import annotations

import queue
import re
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

from src.agent import ProjectAgent
from src.agent.mentions import completion_data
from src.agent.skills import skill_names
from . import docs_viewer
from .skill_dialog import open_project_skills
from .layout import fit_window


class AgentPanel(ttk.Frame):
    

    def __init__(self, parent, on_files_changed=None):
        super().__init__(parent, padding=(8, 6))
        self.on_files_changed = on_files_changed
        self.agent: ProjectAgent | None = None
        self.root_path: Path | None = None
        self.session_id: str | None = None
        self._queue: queue.Queue = queue.Queue()
        self._completion = {'file': []}
        self._running = False
        self._session_revision = (0, 0)
        self._prepared_skills: list[str] = []
        self._build()
        self.after(120, self._poll)

    def _build(self):
        header = ttk.Frame(self)
        header.pack(fill=tk.X)
        ttk.Label(header, text='AI', font=('Microsoft YaHei UI', 11, 'bold')).pack(side=tk.LEFT)
        ttk.Button(header, text='新对话', width=7, command=self._new_session).pack(side=tk.RIGHT)
        self.project_skill_btn = ttk.Button(header, text='项目Skill', width=8, command=self._open_project_skills)
        
        self.project_skill_btn.pack(side=tk.RIGHT, padx=(0, 4))
        self.more_btn = ttk.Button(header, text='⋯', width=3, command=self._show_more_menu)
        self.more_btn.pack(side=tk.RIGHT, padx=(0, 4))

        self.session_var = tk.StringVar()
        self.session_combo = ttk.Combobox(self, textvariable=self.session_var, state='readonly', width=1)
        self.session_combo.pack(fill=tk.X, pady=(6, 5))
        self.session_combo.bind('<<ComboboxSelected>>', self._session_selected)

        transcript_frame = ttk.Frame(self)
        transcript_frame.pack(fill=tk.BOTH, expand=True)
        self.transcript = tk.Text(
            transcript_frame, width=1, height=8, wrap=tk.WORD,
            state=tk.DISABLED, font=('Microsoft YaHei UI', 9),
            borderwidth=1, relief=tk.SOLID,
        )
        transcript_scroll = ttk.Scrollbar(transcript_frame, orient=tk.VERTICAL, command=self.transcript.yview)
        self.transcript.configure(yscrollcommand=transcript_scroll.set)
        self.transcript.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        transcript_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.input = tk.Text(
            self, width=1, height=5, wrap=tk.WORD,
            font=('Microsoft YaHei UI', 9), borderwidth=1, relief=tk.SOLID,
        )
        self.input.pack(fill=tk.X, pady=(6, 0))
        self.input.bind('<KeyRelease>', self._on_key_release)
        self.input.bind('<Control-Return>', lambda _e: self._send())

        self.suggest_frame = ttk.Frame(self)
        self.suggest_list = tk.Listbox(self.suggest_frame, width=1, height=5)
        self.suggest_list.pack(fill=tk.X)
        self.suggest_list.bind('<Double-Button-1>', self._accept_suggestion)
        self.suggest_list.bind('<Return>', self._accept_suggestion)
        self._suggest_context: tuple[int, int] | None = None

        footer = ttk.Frame(self)
        self.footer = footer
        footer.pack(fill=tk.X, pady=(6, 0))
        self.status = ttk.Label(footer, text='')
        self.status.pack(side=tk.LEFT)
        self.send_btn = ttk.Button(footer, text='发送', width=8, command=self._send, state=tk.DISABLED)
        self.send_btn.pack(side=tk.RIGHT)
        self.cancel_btn = ttk.Button(footer, text='停止', width=7, command=self._cancel, state=tk.DISABLED)
        

    def _show_more_menu(self):
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label='重命名当前对话', command=self._rename_session)
        menu.add_command(label='删除当前对话', command=self._delete_session)
        menu.add_separator()
        menu.add_command(label='撤销最近一次 AI 写回', command=self._undo_last)
        menu.add_separator()
        menu.add_command(label='AI 使用帮助', command=lambda: docs_viewer.open_docs('agent-workbench'))
        try:
            x = self.more_btn.winfo_rootx()
            y = self.more_btn.winfo_rooty() + self.more_btn.winfo_height()
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def set_workspace(self, root: str | Path | None):
        self._prepared_skills = []
        if not root:
            self.agent = None
            self.root_path = None
            self.session_id = None
            self.send_btn.configure(state=tk.DISABLED)
            self.cancel_btn.configure(state=tk.DISABLED)
            self.project_skill_btn.configure(state=tk.DISABLED)
            self.status.configure(text='')
            self._session_revision = (0, 0)
            self.session_combo['values'] = []
            self.session_var.set('')
            self._clear_transcript()
            return
        self.root_path = Path(root).resolve()
        self.agent = ProjectAgent(self.root_path)
        self.send_btn.configure(state=tk.NORMAL)
        self.project_skill_btn.configure(state=tk.NORMAL)
        self.status.configure(text='')
        self._refresh_sessions(select_first=True)
        self._session_revision = self.agent.sessions.revision()
        self._refresh_completion()

    def insert_file(self, path: str | Path):
        if not self.root_path:
            return
        target = Path(path).resolve()
        try:
            rel = target.relative_to(self.root_path).as_posix()
        except ValueError:
            return
        token = f'@file "{rel}" ' if ' ' in rel else f'@file {rel} '
        existing = self.input.get('1.0', 'end').strip()
        if token.strip() not in existing:
            if existing and not existing.endswith((' ', '\n')):
                self.input.insert(tk.END, '\n')
            self.input.insert(tk.END, token)
        self.input.focus_set()

    def prepare_file_task(self, path: str | Path, *, skill: str = '', prompt: str = ''):
        
        self.insert_file(path)
        if skill in {'summarize', 'polish'} and skill not in self._prepared_skills:
            self._prepared_skills.append(skill)
        if prompt:
            existing = self.input.get('1.0', 'end').strip()
            spacer = '' if not existing else '\n'
            self.input.insert(tk.END, spacer + prompt)
        self.input.focus_set()

    def _refresh_sessions(self, select_first=False, select_latest=False):
        if not self.agent:
            self.session_combo['values'] = []
            self._session_items = []
            return
        sessions = self.agent.sessions.list()
        self._session_items = sessions
        values = [item.title for item in sessions]
        self.session_combo['values'] = values
        self._session_revision = self.agent.sessions.revision()
        if not sessions:
            self.session_id = None
            self.session_var.set('')
            self._clear_transcript()
            return
        idx = None
        if select_latest:
            idx = 0
        elif self.session_id:
            for i, item in enumerate(sessions):
                if item.id == self.session_id:
                    idx = i
                    break
        elif select_first:
            idx = 0
        if idx is None:
            return
        self.session_combo.current(idx)
        self.session_id = sessions[idx].id
        self._load_transcript()

    def _open_project_skills(self):
        if not self.root_path:
            return
        open_project_skills(self, self.root_path)

    def _new_session(self):
        if not self.agent:
            return
        self.session_id = None
        self.session_var.set('')
        self._prepared_skills = []
        self._clear_transcript()
        self.input.delete('1.0', tk.END)
        self.input.focus_set()

    def _rename_session(self):
        if not self.agent or not self.session_id:
            return
        current = self.agent.sessions.info(self.session_id)
        title = simpledialog.askstring('重命名对话', '标题', initialvalue=current.title if current else '', parent=self)
        if title:
            self.agent.sessions.rename(self.session_id, title)
            self._refresh_sessions()

    def _delete_session(self):
        if not self.agent or not self.session_id:
            return
        if not messagebox.askyesno('删除对话', '确定删除当前 AI 对话记录吗？', parent=self):
            return
        self.agent.sessions.delete(self.session_id)
        self.session_id = None
        self._refresh_sessions(select_first=True)

    def _undo_last(self):
        if not self.agent:
            return
        backup = self.agent.latest_backup()
        if not backup:
            messagebox.showinfo('撤销 AI 写回', '当前项目没有可撤销的 AI 写回。', parent=self)
            return
        if (backup / 'UNDONE').exists():
            messagebox.showinfo('撤销 AI 写回', '最近一次 AI 写回已经撤销。', parent=self)
            return
        if not messagebox.askyesno('撤销 AI 写回', '恢复最近一次写回前的文件状态？', parent=self):
            return
        try:
            restored = self.agent.undo_backup(backup)
            self.status.configure(text=f'已撤销 {len(restored)} 个文件')
            if self.on_files_changed:
                self.on_files_changed()
        except Exception as exc:
            messagebox.showerror('撤销 AI 写回', str(exc), parent=self)

    def _session_selected(self, _event=None):
        idx = self.session_combo.current()
        if 0 <= idx < len(getattr(self, '_session_items', [])):
            self.session_id = self._session_items[idx].id
            self._load_transcript()

    def _load_transcript(self):
        self._clear_transcript()
        if not self.agent or not self.session_id:
            return
        for item in self.agent.sessions.read(self.session_id):
            role = item.get('role', '')
            if role not in {'user', 'assistant'}:
                continue
            prefix = '你' if role == 'user' else 'AI'
            self._append_transcript(prefix, str(item.get('content') or ''))

    def _clear_transcript(self):
        self.transcript.configure(state=tk.NORMAL)
        self.transcript.delete('1.0', tk.END)
        self.transcript.configure(state=tk.DISABLED)

    def _append_transcript(self, speaker: str, text: str):
        self.transcript.configure(state=tk.NORMAL)
        if self.transcript.index('end-1c') != '1.0':
            self.transcript.insert(tk.END, '\n')
        self.transcript.insert(tk.END, f'{speaker}\n{text.strip()}\n')
        self.transcript.configure(state=tk.DISABLED)
        self.transcript.see(tk.END)

    def _send(self):
        if not self.agent:
            return
        message = self.input.get('1.0', 'end').strip()
        if not message:
            return
        extra_skills = tuple(self._prepared_skills)
        self._prepared_skills = []
        self._append_transcript('你', message)
        self.input.delete('1.0', tk.END)
        self._running = True
        self.send_btn.configure(state=tk.DISABLED)
        self.cancel_btn.configure(state=tk.NORMAL)
        self.cancel_btn.pack(side=tk.RIGHT, padx=(0, 5))
        self.status.configure(text='处理中…')
        self._streamed_chars = 0
        self._append_transcript_header('AI')
        requested_session = self.session_id

        def worker():
            try:
                result = self.agent.run(
                    message,
                    session_id=requested_session,
                    extra_skills=extra_skills,
                    on_text=lambda text: self._queue.put(('stream', text)),
                )
                self._queue.put(('done', result))
            except Exception as exc:
                self._queue.put(('error', str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _poll(self):
        try:
            while True:
                item = self._queue.get_nowait()
                if item[0] == 'stream':
                    self._append_stream_text(str(item[1]))
                elif item[0] == 'done':
                    result = item[1]
                    self.session_id = result.session_id
                    if not getattr(self, '_streamed_chars', 0) and result.output:
                        self._append_stream_text(result.output)
                    self._append_stream_text('\n')
                    self._running = False
                    self.status.configure(text='')
                    self.send_btn.configure(state=tk.NORMAL)
                    self.cancel_btn.pack_forget()
                    self.cancel_btn.configure(state=tk.DISABLED)
                    if result.pending_changes:
                        self._show_diff(result.pending_changes)
                    self._refresh_sessions()
                    self._refresh_completion()
                else:
                    self._running = False
                    self.status.configure(text='')
                    self.send_btn.configure(state=tk.NORMAL)
                    self.cancel_btn.pack_forget()
                    self.cancel_btn.configure(state=tk.DISABLED)
                    messagebox.showerror('AI', item[1], parent=self)
        except queue.Empty:
            pass
        self._poll_external_sessions()
        self.after(120, self._poll)

    def _poll_external_sessions(self):
        if not self.agent or self._running:
            return
        revision = self.agent.sessions.revision()
        if revision == self._session_revision:
            return
        previous_ids = {item.id for item in getattr(self, '_session_items', [])}
        sessions = self.agent.sessions.list()
        new_ids = [item.id for item in sessions if item.id not in previous_ids]
        self._session_revision = revision
        if new_ids:
            self.session_id = new_ids[0]
            self._refresh_sessions(select_latest=True)
        else:
            self._refresh_sessions()
            if self.session_id:
                self._load_transcript()

    def _append_transcript_header(self, speaker: str):
        self.transcript.configure(state=tk.NORMAL)
        if self.transcript.index('end-1c') != '1.0':
            self.transcript.insert(tk.END, '\n')
        self.transcript.insert(tk.END, f'{speaker}\n')
        self.transcript.configure(state=tk.DISABLED)
        self.transcript.see(tk.END)

    def _append_stream_text(self, text: str):
        self._streamed_chars = getattr(self, '_streamed_chars', 0) + len(text)
        self.transcript.configure(state=tk.NORMAL)
        self.transcript.insert(tk.END, text)
        self.transcript.configure(state=tk.DISABLED)
        self.transcript.see(tk.END)

    def _cancel(self):
        if self.agent and self.agent.cancel():
            self.status.configure(text='正在停止…')
            self.cancel_btn.configure(state=tk.DISABLED)

    def _show_diff(self, changes):
        if not self.agent:
            return
        dialog = tk.Toplevel(self)
        dialog.title('AI 文件改动')
        fit_window(dialog, 980, 720, min_width=680, min_height=500)
        dialog.transient(self.winfo_toplevel())
        text_frame = ttk.Frame(dialog, padding=(10, 10, 10, 0))
        text_frame.pack(fill=tk.BOTH, expand=True)
        text = tk.Text(text_frame, width=1, wrap=tk.NONE, font=('Cascadia Code', 9))
        ybar = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=text.yview)
        xbar = ttk.Scrollbar(text_frame, orient=tk.HORIZONTAL, command=text.xview)
        text.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        text.grid(row=0, column=0, sticky=tk.NSEW)
        ybar.grid(row=0, column=1, sticky=tk.NS)
        xbar.grid(row=1, column=0, sticky=tk.EW)
        text_frame.rowconfigure(0, weight=1)
        text_frame.columnconfigure(0, weight=1)
        for change in changes:
            text.insert(tk.END, f'\n===== {change.kind.upper()} {change.relative_path} =====\n')
            text.insert(tk.END, change.text_diff() + '\n')
        text.configure(state=tk.DISABLED)
        row = ttk.Frame(dialog, padding=(10, 0, 10, 10))
        row.pack(fill=tk.X)

        def apply():
            try:
                self.agent.apply_changes(changes)
                compiled = self.agent.recompile_changed_latex(changes)
                dialog.destroy()
                text = '已写回'
                if compiled:
                    text += f'，已重编译 PDF ×{len(compiled)}'
                self.status.configure(text=text)
                if self.on_files_changed:
                    self.on_files_changed()
            except Exception as exc:
                messagebox.showerror('AI 改动', str(exc), parent=dialog)

        ttk.Button(row, text='放弃', command=dialog.destroy).pack(side=tk.RIGHT)
        ttk.Button(row, text='确认写回', command=apply).pack(side=tk.RIGHT, padx=8)

    def _refresh_completion(self):
        if not self.agent or not self.root_path:
            self._completion = {'file': [], 'skill': []}
            return
        self._completion = completion_data(self.root_path)
        self._completion['skill'] = skill_names(self.root_path)

    def _on_key_release(self, event=None):
        if event and event.keysym in {'Up', 'Down', 'Return', 'Escape'}:
            if event.keysym == 'Escape':
                self.suggest_frame.pack_forget()
            return
        text = self.input.get('1.0', 'insert')
        match = re.search(r'@(file|skill)(?:\s+([^@\n]*))?$', text)
        if not match:
            self.suggest_frame.pack_forget()
            return
        kind = match.group(1).casefold()
        fragment = (match.group(2) or '').strip().strip('"\'')
        pool = self._completion.get('skill', []) if kind == 'skill' else self._completion.get('file', [])
        suggestions = [v for v in pool if fragment.casefold() in v.casefold()][:40]
        if not suggestions:
            self.suggest_frame.pack_forget()
            return
        self.suggest_list.delete(0, tk.END)
        for value in suggestions:
            self.suggest_list.insert(tk.END, value)
        self._suggest_context = (match.start(), len(text))
        self._suggest_kind = kind
        self.suggest_frame.pack(fill=tk.X, before=self.footer)

    def _accept_suggestion(self, _event=None):
        if not self._suggest_context:
            return
        selection = self.suggest_list.curselection()
        if not selection:
            return
        value = self.suggest_list.get(selection[0])
        start, end = self._suggest_context
        kind = getattr(self, '_suggest_kind', 'file')
        formatted = f'"{value}"' if ' ' in value else value
        replacement = f'@{kind} {formatted} '
        start_idx = self.input.index(f'1.0+{start}c')
        end_idx = self.input.index(f'1.0+{end}c')
        self.input.delete(start_idx, end_idx)
        self.input.insert(start_idx, replacement)
        self.suggest_frame.pack_forget()
        self.input.focus_set()
