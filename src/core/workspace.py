from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Iterable


WORK_DIR_NAME = '.workknacks'
PROCESSING_CATEGORIES = ('translate', 'transcribe', 'parse')
DOCUMENT_EXTENSIONS = {
    '.md', '.txt', '.tex', '.srt', '.vtt', '.pdf', '.doc', '.docx',
    '.ppt', '.pptx', '.xls', '.xlsx', '.csv', '.json', '.png', '.jpg',
    '.jpeg', '.webp', '.mp3', '.wav', '.m4a', '.mp4', '.mkv', '.mov',
}


def _now() -> str:
    return datetime.now().isoformat(timespec='seconds')


class ProjectWorkspace:
    """A local project folder plus its private WorkKnacks bookkeeping."""

    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root).expanduser().resolve()
        self.internal_dir = self.root / WORK_DIR_NAME
        self.state_path = self.internal_dir / 'state.json'
        self.progress_path = self.internal_dir / 'progress.json'
        self.usage_path = self.internal_dir / 'usage.json'
        self.ai_log_dir = self.internal_dir / 'ai-logs'
        self.state = self._load_state()

    def ensure(self) -> 'ProjectWorkspace':
        if not self.root.exists():
            self.root.mkdir(parents=True)
        if not self.root.is_dir():
            raise NotADirectoryError(str(self.root))
        self.internal_dir.mkdir(parents=True, exist_ok=True)
        self.ai_log_dir.mkdir(parents=True, exist_ok=True)
        if not self.state_path.exists():
            self.save()
        return self

    def _load_state(self) -> dict:
        if not self.state_path.exists():
            return self._new_state()
        try:
            data = json.loads(self.state_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            return self._new_state()
        if not isinstance(data, dict):
            return self._new_state()
        data.setdefault('version', 1)
        data.setdefault('project_path', str(self.root))
        data.setdefault('updated_at', _now())
        data.setdefault('files', {})
        return data

    def _new_state(self) -> dict:
        return {
            'version': 1,
            'project_path': str(self.root),
            'updated_at': _now(),
            'files': {},
        }

    def save(self) -> None:
        self.ensure_dir()
        self.state['project_path'] = str(self.root)
        self.state['updated_at'] = _now()
        temp_path = self.state_path.with_suffix('.tmp')
        temp_path.write_text(
            json.dumps(self.state, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )
        temp_path.replace(self.state_path)

    def ensure_dir(self) -> None:
        self.internal_dir.mkdir(parents=True, exist_ok=True)

    def relative_path(self, path: str | os.PathLike[str]) -> str:
        return Path(os.path.relpath(Path(path).resolve(), self.root)).as_posix()

    def absolute_path(self, relative_path: str) -> Path:
        return (self.root / relative_path).resolve()

    def _generated_outputs(self) -> set[Path]:
        generated = set()
        for entry in self.state.get('files', {}).values():
            for action in entry.values():
                for output in action.get('outputs', []):
                    generated.add(Path(output).resolve())
        return generated

    def iter_documents(self) -> list[Path]:
        if not self.root.exists():
            return []
        generated_files = self._generated_outputs()
        documents = []
        for path in self.root.rglob('*'):
            if not path.is_file():
                continue
            relative_parts = path.relative_to(self.root).parts
            if WORK_DIR_NAME in relative_parts:
                continue
            if path.resolve() in generated_files:
                continue
            if path.suffix.lower() in DOCUMENT_EXTENSIONS:
                documents.append(path)
        return sorted(documents, key=lambda item: (item.name.lower(), str(item).lower()))

    def list_dir(self, relative: str = '') -> tuple[list[Path], list[Path]]:
        """列出 relative 目录下的子文件夹与文档文件（不递归）。

        用于资源管理器式导航；跳过 .workknacks、隐藏项和已记录的处理结果。
        """

        base = self.root if not relative else (self.root / relative)
        if not base.is_dir():
            return [], []
        generated = self._generated_outputs()
        folders, docs = [], []
        for child in sorted(base.iterdir(),
                            key=lambda p: (p.is_file(), p.name.lower())):
            name = child.name
            if name == WORK_DIR_NAME or name.startswith('.'):
                continue
            if child.is_dir():
                folders.append(child)
            elif (child.is_file()
                  and child.suffix.lower() in DOCUMENT_EXTENSIONS
                  and child.resolve() not in generated):
                docs.append(child)
        return folders, docs

    def output_dir_for(self, source_path: str | os.PathLike[str]) -> Path:
        return Path(source_path).expanduser().resolve().parent

    def translated_path(self, source_path: str | os.PathLike[str]) -> Path:
        source = Path(source_path)
        base, ext = os.path.splitext(source.name)
        return source.resolve().parent / f'{base}-翻译{ext}'

    def file_state(self, path: str | os.PathLike[str]) -> dict:
        return self.state.get('files', {}).get(self.relative_path(path), {})

    def record_action(
        self,
        source_path: str | os.PathLike[str] | None,
        category: str,
        status: str,
        outputs: Iterable[str] = (),
        message: str = '',
    ) -> None:
        if source_path is None:
            key = '_workspace'
        else:
            key = self.relative_path(source_path)
        files = self.state.setdefault('files', {})
        entry = files.setdefault(key, {})
        entry[category] = {
            'status': status,
            'outputs': [str(item) for item in outputs if item],
            'message': message,
            'updated_at': _now(),
        }
        self.save()

    def category_status(self, path: str | os.PathLike[str], category: str) -> str:
        entry = self.file_state(path).get(category, {})
        status = entry.get('status', '')
        if status == 'done':
            outputs = entry.get('outputs', [])
            if outputs and all(self.absolute_path(output).exists()
                               if not Path(output).is_absolute()
                               else Path(output).exists()
                               for output in outputs):
                return '已完成'
            return '待更新'
        if status == 'running':
            return '处理中'
        if status == 'error':
            return '失败'
        return '未处理'

    def summarize(self) -> dict[str, int]:
        summary = {'documents': len(self.iter_documents()), 'processed': 0, 'errors': 0}
        for path in self.iter_documents():
            states = self.file_state(path)
            if any(
                self.category_status(path, category) == '已完成'
                for category in PROCESSING_CATEGORIES
            ):
                summary['processed'] += 1
            if any(value.get('status') == 'error' for value in states.values()):
                summary['errors'] += 1
        return summary
