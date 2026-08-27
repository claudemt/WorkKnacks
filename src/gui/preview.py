import tkinter as tk
from pathlib import Path
from tkinter import ttk

from ..core.runtime import runtime_dir
from .layout import fit_window


class ImagePreview(tk.Toplevel):
    def __init__(self, parent, image_path: str, title: str = '预览'):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        try:
            self.photo = tk.PhotoImage(file=image_path)
        except tk.TclError:
            ttk.Label(self, text='图片无法加载', padding=20).pack()
            return
        w, h = self.photo.width(), self.photo.height()
        screen_w = max(1, self.winfo_screenwidth() - 80)
        screen_h = max(1, self.winfo_screenheight() - 120)
        factor = max(1, int(max(w / screen_w, h / screen_h) + 0.999))
        if factor > 1:
            self.photo = self.photo.subsample(factor, factor)
            w, h = self.photo.width(), self.photo.height()
        fit_window(self, w + 24, h + 70, min_width=min(320, w + 24), min_height=min(200, h + 70))
        ttk.Label(self, image=self.photo).pack(pady=4)
        ttk.Label(self, text='扫码后本窗口自动关闭').pack()


class PdfPreview(tk.Toplevel):
    def __init__(self, parent, pdf_path: str):
        super().__init__(parent)
        self.title(Path(pdf_path).name)
        fit_window(self, 900, 900, min_width=640, min_height=520)
        self.transient(parent)

        try:
            import fitz
        except ImportError:
            try:
                import pymupdf as fitz
            except ImportError:
                ttk.Label(self, text='需要安装 PyMuPDF 才能预览 PDF',
                          padding=20).pack()
                return

        self.fitz = fitz
        self.doc = fitz.open(pdf_path)
        self.page = 0
        self.photo = None

        self.canvas_label = ttk.Label(self)
        self.canvas_label.pack(fill=tk.BOTH, expand=True)

        bar = ttk.Frame(self, padding=8)
        bar.pack(fill=tk.X)
        ttk.Button(bar, text='上一页', command=self._prev).pack(side=tk.LEFT)
        ttk.Button(bar, text='下一页', command=self._next).pack(side=tk.LEFT, padx=6)
        self.page_label = ttk.Label(bar, text='')
        self.page_label.pack(side=tk.LEFT, padx=12)
        ttk.Button(bar, text='关闭',
                   command=self.destroy).pack(side=tk.RIGHT)

        self._render()

    def _render(self):
        if self.photo is not None:
            del self.photo
        page = self.doc[self.page]
        mat = self.fitz.Matrix(0.8, 0.8)
        pix = page.get_pixmap(matrix=mat)
        img_path = runtime_dir() / 'pdf_preview.png'
        img_path.parent.mkdir(parents=True, exist_ok=True)
        pix.save(str(img_path))
        self.photo = tk.PhotoImage(file=str(img_path))
        self.canvas_label.configure(image=self.photo)
        self.page_label.configure(
            text=f'{self.page + 1} / {self.doc.page_count}')

    def _prev(self):
        if self.page > 0:
            self.page -= 1
            self._render()

    def _next(self):
        if self.page < self.doc.page_count - 1:
            self.page += 1
            self._render()

    def destroy(self):
        try:
            self.doc.close()
        except Exception:
            pass
        super().destroy()


def show_image(parent, path, title='预览'):
    return ImagePreview(parent, path, title)


def show_pdf(parent, path):
    return PdfPreview(parent, path)
