from __future__ import annotations

import threading
import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk

from src.library.entry import Creator, LibraryEntry
from .layout import fit_window


ITEM_TYPES = [
    'journalArticle', 'preprint', 'conferencePaper', 'book', 'bookSection',
    'thesis', 'report', 'document',
]
AIReview = Callable[[], tuple[LibraryEntry | None, str]]
AutoRecognize = Callable[[], tuple[LibraryEntry | None, str]]
NetworkSearch = Callable[[LibraryEntry], tuple[LibraryEntry | None, str]]


class EntryDialog(tk.Toplevel):
    def __init__(
        self,
        parent,
        entry: LibraryEntry,
        title: str = '文献信息',
        *,
        ai_review: AIReview | None = None,
        auto_recognize: AutoRecognize | None = None,
        network_search: NetworkSearch | None = None,
        auto_on_open: bool = False,
    ):
        super().__init__(parent)
        self.title(title)
        fit_window(self, 840, 700, min_width=680, min_height=560, vertical_margin=40)
        self.transient(parent)
        self.grab_set()
        self.result: LibraryEntry | None = None
        self.entry = LibraryEntry.from_dict(entry.to_dict())
        self.vars: dict[str, tk.StringVar] = {}
        self.ai_review = ai_review
        self.auto_recognize = auto_recognize
        self.network_search = network_search

        body = ttk.Frame(self, padding=14)
        body.pack(fill=tk.BOTH, expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(3, weight=1, minsize=78)
        body.rowconfigure(5, weight=2, minsize=126)

        title_frame = ttk.Frame(body)
        title_frame.grid(row=0, column=0, sticky=tk.EW)
        title_frame.columnconfigure(1, weight=1)
        ttk.Label(title_frame, text='标题').grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
        self.vars['title'] = tk.StringVar(value=self.entry.title)
        ttk.Entry(title_frame, textvariable=self.vars['title']).grid(row=0, column=1, sticky=tk.EW)

        meta = ttk.LabelFrame(body, text='出版与识别信息', padding=(10, 7))
        meta.grid(row=1, column=0, sticky=tk.EW, pady=(10, 8))
        meta.columnconfigure(1, weight=1)
        meta.columnconfigure(3, weight=1)
        pairs = [
            (('item_type', '类型', self.entry.item_type), ('year', '年份', self.entry.year or '')),
            (('publication', '期刊/出处', self.entry.publication_title), ('publisher', '出版社', self.entry.publisher)),
            (('doi', 'DOI', self.entry.doi), ('arxiv', 'arXiv', self.entry.arxiv_id)),
            (('isbn', 'ISBN', self.entry.isbn), ('edition', '版本', self.entry.edition)),
            (('place', '出版地', self.entry.place), ('language', '语言', self.entry.language)),
        ]
        for row, pair in enumerate(pairs):
            for side, (key, label, value) in enumerate(pair):
                col = side * 2
                ttk.Label(meta, text=label).grid(row=row, column=col, sticky=tk.W, padx=(0 if side == 0 else 12, 7), pady=3)
                var = tk.StringVar(value=str(value))
                self.vars[key] = var
                widget = ttk.Combobox(meta, textvariable=var, values=ITEM_TYPES, state='readonly') if key == 'item_type' else ttk.Entry(meta, textvariable=var)
                widget.grid(row=row, column=col + 1, sticky=tk.EW, pady=3)

        tags_frame = ttk.Frame(body)
        tags_frame.grid(row=2, column=0, sticky=tk.EW, pady=(0, 7))
        tags_frame.columnconfigure(1, weight=1)
        ttk.Label(tags_frame, text='Tags').grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
        self.vars['tags'] = tk.StringVar(value=', '.join(self.entry.tags))
        ttk.Entry(tags_frame, textvariable=self.vars['tags']).grid(row=0, column=1, sticky=tk.EW)

        authors_frame = ttk.LabelFrame(body, text='作者（每行一个；可用 “Family, Given”）', padding=6)
        authors_frame.grid(row=3, column=0, sticky=tk.NSEW, pady=(0, 8))
        authors_frame.columnconfigure(0, weight=1)
        authors_frame.rowconfigure(0, weight=1)
        self.authors = tk.Text(authors_frame, width=1, height=5, wrap=tk.WORD)
        self.authors.grid(row=0, column=0, sticky=tk.NSEW)
        self.authors.insert('1.0', '\n'.join(_creator_line(c) for c in self.entry.authors))

        status_frame = ttk.Frame(body)
        status_frame.grid(row=4, column=0, sticky=tk.EW, pady=(0, 8))
        ttk.Label(status_frame, text='阅读状态').pack(side=tk.LEFT)
        self.status = tk.StringVar(value=self.entry.reading_status or 'unread')
        ttk.Combobox(
            status_frame, textvariable=self.status, state='readonly', width=16,
            values=['unread', 'read', 'deep-read'],
        ).pack(side=tk.LEFT, padx=(8, 0))

        abstract_frame = ttk.LabelFrame(body, text='摘要 / 内容说明', padding=6)
        abstract_frame.grid(row=5, column=0, sticky=tk.NSEW)
        abstract_frame.columnconfigure(0, weight=1)
        abstract_frame.rowconfigure(0, weight=1)
        self.abstract = tk.Text(abstract_frame, width=1, height=6, wrap=tk.WORD)
        self.abstract.grid(row=0, column=0, sticky=tk.NSEW)
        self.abstract.insert('1.0', self.entry.abstract)

        buttons = ttk.Frame(body)
        buttons.grid(row=6, column=0, sticky=tk.EW, pady=(12, 0))
        if auto_recognize:
            self.auto_btn = ttk.Button(buttons, text='自动识别', command=self._start_auto_recognize)
            self.auto_btn.pack(side=tk.LEFT)
        else:
            self.auto_btn = None
        if ai_review:
            self.ai_btn = ttk.Button(buttons, text='AI复核', command=self._start_ai_review)
            self.ai_btn.pack(side=tk.LEFT, padx=(6, 0))
        else:
            self.ai_btn = None
        if network_search:
            self.net_btn = ttk.Button(buttons, text='联网搜索', command=self._start_network_search)
            self.net_btn.pack(side=tk.LEFT, padx=(6, 0))
        else:
            self.net_btn = None
        ttk.Button(buttons, text='取消', command=self._cancel).pack(side=tk.RIGHT)
        ttk.Button(buttons, text='保存', command=self._ok).pack(side=tk.RIGHT, padx=8)
        self.protocol('WM_DELETE_WINDOW', self._cancel)
        if auto_on_open and auto_recognize:
            self.after(120, self._start_auto_recognize)

    def _start_auto_recognize(self):
        if not self.auto_recognize or not self.auto_btn:
            return
        self.auto_btn.configure(state=tk.DISABLED, text='识别中…')

        def worker():
            try:
                entry, summary = self.auto_recognize()
                self.after(0, lambda: self._finish_auto_recognize(entry, summary, None))
            except Exception as exc:
                self.after(0, lambda error=exc: self._finish_auto_recognize(None, '', error))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_auto_recognize(self, entry: LibraryEntry | None, summary: str, error: Exception | None):
        if self.auto_btn and self.winfo_exists():
            self.auto_btn.configure(state=tk.NORMAL, text='自动识别')
        if error:
            messagebox.showerror('自动识别', str(error), parent=self)
            return
        if entry is None:
            messagebox.showinfo('自动识别', summary or '没有识别到可靠元数据。', parent=self)
            return
        self.entry = LibraryEntry.from_dict(entry.to_dict())
        self._load_entry()
        if summary:
            messagebox.showinfo('自动识别', summary, parent=self)

    def _start_ai_review(self):
        if not self.ai_review or not self.ai_btn:
            return
        self.ai_btn.configure(state=tk.DISABLED, text='AI复核中…')

        def worker():
            try:
                entry, summary = self.ai_review()
                self.after(0, lambda: self._finish_ai_review(entry, summary, None))
            except Exception as exc:
                self.after(0, lambda error=exc: self._finish_ai_review(None, '', error))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_ai_review(self, entry: LibraryEntry | None, summary: str, error: Exception | None):
        if self.ai_btn and self.winfo_exists():
            self.ai_btn.configure(state=tk.NORMAL, text='AI复核')
        if error:
            messagebox.showerror('AI复核', str(error), parent=self)
            return
        if entry is None:
            messagebox.showinfo('AI复核', summary or '未找到足够可靠的元数据候选。', parent=self)
            return
        text = summary.strip() or _entry_summary(entry)
        if messagebox.askyesno('AI复核', text + '\n\n采纳这份推荐元数据吗？', parent=self):
            self.entry = LibraryEntry.from_dict(entry.to_dict())
            self._load_entry()

    def _start_network_search(self):
        if not self.network_search or not self.net_btn:
            return
        self.net_btn.configure(state=tk.DISABLED, text='搜索中…')

        def worker():
            try:
                entry, summary = self.network_search(self.entry)
                self.after(0, lambda: self._finish_network_search(entry, summary, None))
            except Exception as exc:
                self.after(0, lambda error=exc: self._finish_network_search(None, '', error))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_network_search(self, entry: LibraryEntry | None, summary: str, error: Exception | None):
        if self.net_btn and self.winfo_exists():
            self.net_btn.configure(state=tk.NORMAL, text='联网搜索')
        if error:
            messagebox.showerror('联网搜索', str(error), parent=self)
            return
        if entry is None:
            messagebox.showinfo('联网搜索', summary or '未命中网络元数据。', parent=self)
            return
        text = summary.strip()
        if messagebox.askyesno('联网搜索', text + '\n\n采纳这份补全吗？', parent=self):
            self.entry = LibraryEntry.from_dict(entry.to_dict())
            self._load_entry()

    def _load_entry(self):
        mapping = {
            'title': self.entry.title,
            'item_type': self.entry.item_type,
            'year': self.entry.year or '',
            'publication': self.entry.publication_title,
            'publisher': self.entry.publisher,
            'doi': self.entry.doi,
            'arxiv': self.entry.arxiv_id,
            'isbn': self.entry.isbn,
            'edition': self.entry.edition,
            'place': self.entry.place,
            'language': self.entry.language,
            'tags': ', '.join(self.entry.tags),
        }
        for key, value in mapping.items():
            if key in self.vars:
                self.vars[key].set(str(value or ''))
        self.authors.delete('1.0', tk.END)
        self.authors.insert('1.0', '\n'.join(_creator_line(c) for c in self.entry.authors))
        self.abstract.delete('1.0', tk.END)
        self.abstract.insert('1.0', self.entry.abstract)
        self.status.set(self.entry.reading_status or 'unread')

    def _ok(self):
        title = self.vars['title'].get().strip()
        if not title:
            messagebox.showwarning('信息', '标题不能为空。', parent=self)
            return
        self.entry.title = title
        self.entry.item_type = self.vars['item_type'].get().strip() or 'document'
        year = self.vars['year'].get().strip()
        self.entry.year = int(year) if year.isdigit() and len(year) == 4 else year or None
        self.entry.publication_title = self.vars['publication'].get().strip()
        self.entry.publisher = self.vars['publisher'].get().strip()
        self.entry.place = self.vars['place'].get().strip()
        self.entry.edition = self.vars['edition'].get().strip()
        self.entry.isbn = self.vars['isbn'].get().strip()
        self.entry.doi = self.vars['doi'].get().strip()
        self.entry.arxiv_id = self.vars['arxiv'].get().strip()
        self.entry.language = self.vars['language'].get().strip()
        self.entry.tags = [tag.strip() for tag in self.vars['tags'].get().replace('，', ',').split(',') if tag.strip()]
        self.entry.creators = [Creator.from_any(line.strip()) for line in self.authors.get('1.0', 'end').splitlines() if line.strip()]
        self.entry.abstract = self.abstract.get('1.0', 'end').strip()
        self.entry.reading_status = self.status.get()
        self.entry.touch()
        self.result = self.entry
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


def show_entry_dialog(
    parent,
    entry: LibraryEntry,
    title: str = '文献信息',
    *,
    ai_review: AIReview | None = None,
    auto_recognize: AutoRecognize | None = None,
    network_search: NetworkSearch | None = None,
    auto_on_open: bool = False,
) -> LibraryEntry | None:
    dialog = EntryDialog(
        parent, entry, title=title, ai_review=ai_review,
        auto_recognize=auto_recognize, network_search=network_search, auto_on_open=auto_on_open,
    )
    parent.wait_window(dialog)
    return dialog.result


def _creator_line(creator: Creator) -> str:
    return f'{creator.family}, {creator.given}'.strip(', ') if creator.given else creator.family


def _entry_summary(entry: LibraryEntry) -> str:
    authors = ', '.join(c.display() for c in entry.authors[:4])
    identifier = entry.doi or entry.arxiv_id or entry.isbn or '—'
    return '\n'.join([
        f'标题：{entry.title or "—"}',
        f'作者：{authors or "—"}',
        f'年份：{entry.year or "—"}',
        f'出处：{entry.publication_title or entry.publisher or "—"}',
        f'DOI / arXiv / ISBN：{identifier}',
    ])
