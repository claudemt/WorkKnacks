from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


PARSED_DIRNAME = 'parsed'
TRANSLATIONS_DIRNAME = 'translations'
NOTES_DIRNAME = 'notes'


def _safe_lang(value: str) -> str:
    text = re.sub(r'[^A-Za-z0-9._-]+', '-', str(value or '').strip())
    return text.strip('-') or 'translated'


@dataclass(frozen=True, slots=True)
class ArtifactLayout:


    source: Path

    @classmethod
    def for_source(cls, source: str | Path) -> 'ArtifactLayout':
        return cls(Path(source).expanduser().resolve())

    @property
    def folder(self) -> Path:
        return self.source.parent

    @property
    def root(self) -> Path:
        return self.folder

    @property
    def parsed_root(self) -> Path:
        return self.folder / PARSED_DIRNAME

    @property
    def translations_root(self) -> Path:
        return self.folder / TRANSLATIONS_DIRNAME

    @property
    def notes_root(self) -> Path:
        return self.folder / NOTES_DIRNAME

    @property
    def parse_dir(self) -> Path:
        return self.parsed_root / self.source.stem

    @property
    def parsed_tex(self) -> Path:
        return self.parse_dir / 'main.tex'

    @property
    def parsed_pdf(self) -> Path:
        return self.parse_dir / 'main.pdf'

    @property
    def figures_dir(self) -> Path:
        return self.parse_dir / 'figures'

    def translation_path(self, target_lang: str = 'zh-Hans', suffix: str = '.md') -> Path:
        suffix = suffix if str(suffix).startswith('.') else f'.{suffix}'
        return self.translations_root / f'{self.source.stem}.{_safe_lang(target_lang)}{suffix}'

    def note_path(self, kind: str = 'summary') -> Path:
        kind = re.sub(r'[^A-Za-z0-9._-]+', '-', str(kind or 'summary')).strip('-') or 'summary'
        return self.notes_root / f'{self.source.stem}.{kind}.md'

    def next_manual_note(self) -> Path:
        self.ensure_notes()
        for index in range(1, 10000):
            candidate = self.notes_root / f'note{index:02d}.md'
            if not candidate.exists():
                return candidate
        raise RuntimeError('notes/ 中可用的 noteXX.md 名称已耗尽')

    def ensure_parse_dir(self) -> Path:
        self.parse_dir.mkdir(parents=True, exist_ok=True)
        return self.parse_dir

    def ensure_translations(self) -> Path:
        self.translations_root.mkdir(parents=True, exist_ok=True)
        return self.translations_root

    def ensure_notes(self) -> Path:
        self.notes_root.mkdir(parents=True, exist_ok=True)
        return self.notes_root


def artifact_relpath(folder: str | Path, path: str | Path) -> str:
    base = Path(folder).expanduser().resolve()
    target = Path(path).expanduser().resolve()
    return target.relative_to(base).as_posix()
