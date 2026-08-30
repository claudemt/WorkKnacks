from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from threading import RLock

from .entry import LibraryEntry, normalize_doi
from .rename import DEFAULT_RENAME_TEMPLATE
from src.core.project_paths import ProjectPaths


INDEX_VERSION = 3


def _now() -> str:
    return datetime.now().isoformat(timespec='seconds')


class LibraryIndex:


    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root).expanduser().resolve()
        self.paths = ProjectPaths.for_root(self.root)
        self.internal_dir = self.paths.state
        self.path = self.paths.index
        self._lock = RLock()
        self.data = self._load()

    @staticmethod
    def _new() -> dict:
        return {
            'version': INDEX_VERSION,
            'renameTemplate': DEFAULT_RENAME_TEMPLATE,
            'mappings': {},
            'entries': {},
            'updatedAt': _now(),
        }

    def _load(self) -> dict:
        if not self.path.exists():
            return self._new()
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):

            return self._new()
        if not isinstance(data, dict) or int(data.get('version') or 0) != INDEX_VERSION:
            return self._new()
        fresh = self._new()
        fresh.update(data)
        fresh.setdefault('mappings', {})
        fresh.setdefault('entries', {})
        fresh.setdefault('renameTemplate', DEFAULT_RENAME_TEMPLATE)
        return fresh

    def reload(self) -> 'LibraryIndex':
        with self._lock:
            self.data = self._load()
        return self

    def save(self) -> None:
        with self._lock:
            self.internal_dir.mkdir(parents=True, exist_ok=True)
            self.data['version'] = INDEX_VERSION
            self.data['updatedAt'] = _now()
            temp = self.path.with_suffix('.json.tmp')
            payload = json.dumps(self.data, ensure_ascii=False, indent=2, sort_keys=False)
            temp.write_text(payload, encoding='utf-8')
            if self.path.exists():

                try:
                    json.loads(self.path.read_text(encoding='utf-8'))
                except Exception:
                    pass
                else:
                    backup = self.path.with_suffix('.json.bak')
                    try:
                        backup.write_bytes(self.path.read_bytes())
                    except OSError:
                        pass
            temp.replace(self.path)

    @property
    def rename_template(self) -> str:
        return str(self.data.get('renameTemplate') or DEFAULT_RENAME_TEMPLATE)

    @rename_template.setter
    def rename_template(self, template: str) -> None:
        self.data['renameTemplate'] = str(template or DEFAULT_RENAME_TEMPLATE)
        self.save()

    def entries(self) -> list[LibraryEntry]:
        result = []
        for raw in self.data.get('entries', {}).values():
            try:
                result.append(LibraryEntry.from_dict(raw))
            except Exception:
                continue
        return result

    def get(self, entry_id: str) -> LibraryEntry | None:
        raw = self.data.get('entries', {}).get(entry_id)
        return LibraryEntry.from_dict(raw) if isinstance(raw, dict) else None

    def upsert(self, entry: LibraryEntry, save: bool = True) -> LibraryEntry:
        entry.touch()
        self.data.setdefault('entries', {})[entry.id] = entry.to_dict()
        if save:
            self.save()
        return entry

    def remove(self, entry_id: str, save: bool = True) -> None:
        self.data.setdefault('entries', {}).pop(entry_id, None)
        mappings = self.data.setdefault('mappings', {})
        for key in [k for k, value in mappings.items() if value.get('entryId') == entry_id]:
            mappings.pop(key, None)
        if save:
            self.save()

    def record_mapping(
        self,
        relative_pdf: str,
        *,
        entry: LibraryEntry,
        original_name: str,
        folder: str,
        status: str = 'organized',
        save: bool = True,
    ) -> None:
        key = Path(relative_pdf).as_posix()
        self.data.setdefault('mappings', {})[key] = {
            'status': status,
            'entryId': entry.id,
            'originalName': original_name,
            'folder': folder,
            'movedAt': _now(),
        }
        if save:
            self.save()

    def mark_failed(self, relative_pdf: str, message: str = '') -> None:
        key = Path(relative_pdf).as_posix()
        self.data.setdefault('mappings', {})[key] = {
            'status': 'failed',
            'entryId': '',
            'originalName': Path(relative_pdf).name,
            'folder': '',
            'movedAt': _now(),
            'message': message,
        }
        self.save()

    def mapping_for(self, path: str | os.PathLike[str]) -> dict | None:
        p = Path(path)
        if p.is_absolute():
            try:
                key = p.resolve().relative_to(self.root).as_posix()
            except ValueError:
                return None
        else:
            key = p.as_posix()
        direct = self.data.get('mappings', {}).get(key)
        return deepcopy(direct) if direct else None

    def entry_for_path(self, path: str | os.PathLike[str]) -> LibraryEntry | None:
        mapping = self.mapping_for(path)
        if mapping and mapping.get('entryId'):
            return self.get(str(mapping['entryId']))
        p = Path(path)
        rel = None
        try:
            rel = p.resolve().relative_to(self.root).as_posix()
        except Exception:
            pass
        for entry in self.entries():
            candidates: list[str] = []
            for value in entry.files.values():
                if isinstance(value, str) and value:
                    candidates.append(value)
                elif isinstance(value, list):
                    candidates.extend(str(item) for item in value if item)
            candidates.extend(item.path for item in entry.attachments if item.path)
            for value in candidates:
                candidate = (Path(entry.folder) / value).as_posix() if entry.folder else Path(value).as_posix()
                if rel == candidate or p.name == Path(value).name:
                    return entry
        return None

    def remap_folder_prefix(self, old_relative: str, new_relative: str, save: bool = True) -> int:

        old = Path(old_relative).as_posix().strip('/')
        new = Path(new_relative).as_posix().strip('/')
        if not old or not new:
            return 0
        changed = 0
        entries = self.data.setdefault('entries', {})
        for entry_id, raw in list(entries.items()):
            folder = Path(str(raw.get('folder') or '')).as_posix().strip('/')
            if folder == old or folder.startswith(old + '/'):
                suffix = folder[len(old):].lstrip('/')
                raw['folder'] = new + (('/' + suffix) if suffix else '')
                changed += 1
        mappings = self.data.setdefault('mappings', {})
        moved = {}
        for key, mapping in list(mappings.items()):
            rel = Path(key).as_posix().strip('/')
            if rel == old or rel.startswith(old + '/'):
                suffix = rel[len(old):].lstrip('/')
                new_key = new + (('/' + suffix) if suffix else '')
                mappings.pop(key, None)
                mapping['folder'] = str(mapping.get('folder') or '')
                folder = Path(mapping['folder']).as_posix().strip('/')
                if folder == old or folder.startswith(old + '/'):
                    fsuffix = folder[len(old):].lstrip('/')
                    mapping['folder'] = new + (('/' + fsuffix) if fsuffix else '')
                moved[new_key] = mapping
        mappings.update(moved)
        if changed or moved:
            if save:
                self.save()
        return changed

    def remove_folder_prefix(self, relative: str, save: bool = True) -> int:

        prefix = Path(relative).as_posix().strip('/')
        if not prefix:
            return 0
        entries = self.data.setdefault('entries', {})
        removed_ids = []
        for entry_id, raw in list(entries.items()):
            folder = Path(str(raw.get('folder') or '')).as_posix().strip('/')
            if folder == prefix or folder.startswith(prefix + '/'):
                removed_ids.append(entry_id)
                entries.pop(entry_id, None)
        mappings = self.data.setdefault('mappings', {})
        for key, mapping in list(mappings.items()):
            rel = Path(key).as_posix().strip('/')
            if rel == prefix or rel.startswith(prefix + '/') or mapping.get('entryId') in removed_ids:
                mappings.pop(key, None)
        if removed_ids and save:
            self.save()
        return len(removed_ids)

    def find_duplicate(self, candidate: LibraryEntry, threshold: float = 0.92) -> tuple[LibraryEntry | None, str, float]:
        doi = normalize_doi(candidate.doi)
        normalized_title = _norm_title(candidate.title)
        best: tuple[LibraryEntry | None, str, float] = (None, '', 0.0)
        for existing in self.entries():
            if doi and normalize_doi(existing.doi) == doi:
                return existing, 'doi', 1.0
            if normalized_title and existing.title:
                score = SequenceMatcher(None, normalized_title, _norm_title(existing.title)).ratio()
                if score > best[2]:
                    best = (existing, 'title', score)
        return best if best[2] >= threshold else (None, '', best[2])

    def search(self, query: str) -> list[LibraryEntry]:
        q = str(query or '').strip().casefold()
        if not q:
            return self.entries()
        scored: list[tuple[int, LibraryEntry]] = []
        for entry in self.entries():
            haystacks = [
                entry.title,
                entry.publication_title,
                entry.doi,
                entry.arxiv_id,
                ' '.join(c.display() for c in entry.creators),
                ' '.join(entry.tags),
                ' '.join(entry.keywords),
            ]
            score = sum(1 for value in haystacks if q in str(value).casefold())
            if score:
                scored.append((score, entry))
        return [entry for _, entry in sorted(scored, key=lambda item: (-item[0], item[1].title.casefold()))]

    def self_heal(self) -> int:

        changed = 0
        for rel, mapping in self.data.get('mappings', {}).items():
            if mapping.get('status') not in {'organized', 'supplement'}:
                continue
            if not (self.root / rel).exists():
                mapping['status'] = 'missing'
                mapping['message'] = '文件已被外部移动或删除'
                changed += 1
        if changed:
            self.save()
        return changed


def _norm_title(value: str) -> str:
    return ' '.join(''.join(ch.lower() if ch.isalnum() else ' ' for ch in str(value)).split())
