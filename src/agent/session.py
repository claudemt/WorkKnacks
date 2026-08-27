from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from src.core.project_paths import ProjectPaths


_LOCK_GUARD = threading.Lock()
_STORE_LOCKS: dict[str, threading.RLock] = {}


def _shared_lock(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _LOCK_GUARD:
        lock = _STORE_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _STORE_LOCKS[key] = lock
        return lock


@dataclass(slots=True)
class SessionInfo:
    id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int = 0
    native_started: bool = False


class SessionStore:
    

    VERSION = 4

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.paths = ProjectPaths.for_root(self.root)
        self.dir = self.paths.sessions
        self.meta_path = self.dir / 'index.json'
        self.dir.mkdir(parents=True, exist_ok=True)
        self._lock = _shared_lock(self.meta_path)
        self._meta: dict[str, dict[str, Any]] = {}
        with self._lock:
            self._reload_locked()

    def _load_meta_file(self) -> dict[str, dict[str, Any]]:
        if not self.meta_path.exists():
            return {}
        try:
            data = json.loads(self.meta_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(data, dict):
            return {}
        version = int(data.get('version') or 0)
        if version != self.VERSION:
            return {}
        sessions = data.get('sessions') or {}
        return sessions if isinstance(sessions, dict) else {}

    def _reload_locked(self) -> None:
        self._meta = self._load_meta_file()

    def refresh(self) -> None:
        with self._lock:
            self._reload_locked()

    def _save_meta_locked(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        temp = self.meta_path.with_suffix('.json.tmp')
        temp.write_text(
            json.dumps({'version': self.VERSION, 'sessions': self._meta}, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )
        temp.replace(self.meta_path)

    def create(self, title: str = '新会话') -> SessionInfo:
        with self._lock:
            self._reload_locked()
            now = _now()
            session_id = str(uuid.uuid4())
            self._meta[session_id] = {
                'id': session_id,
                'title': _safe_title(title),
                'created_at': now,
                'updated_at': now,
                'message_count': 0,
                'native_started': False,
            }
            self.path_for(session_id).touch()
            self._save_meta_locked()
            return SessionInfo(**self._meta[session_id])

    def list(self) -> list[SessionInfo]:
        with self._lock:
            self._reload_locked()
            items = [SessionInfo(**value) for value in self._meta.values()]
        return sorted(items, key=lambda item: item.updated_at, reverse=True)

    def info(self, session_id: str) -> SessionInfo | None:
        with self._lock:
            self._reload_locked()
            raw = self._meta.get(session_id)
            return SessionInfo(**raw) if raw else None

    def path_for(self, session_id: str) -> Path:
        try:
            uuid.UUID(str(session_id))
        except ValueError as exc:
            raise ValueError('会话 ID 必须是 UUID') from exc
        return self.dir / f'{session_id}.jsonl'

    def append(self, session_id: str, role: str, content: str, **extra: Any) -> None:
        if role not in {'user', 'assistant', 'system'}:
            raise ValueError('role 必须是 user/assistant/system')
        with self._lock:
            self._reload_locked()
            if session_id not in self._meta:
                raise KeyError(session_id)
            record = {'ts': _now(), 'role': role, 'content': str(content), **extra}
            with self.path_for(session_id).open('a', encoding='utf-8') as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + '\n')
            meta = self._meta[session_id]
            meta['updated_at'] = record['ts']
            meta['message_count'] = int(meta.get('message_count') or 0) + 1
            self._save_meta_locked()

    def mark_native_started(self, session_id: str) -> None:
        with self._lock:
            self._reload_locked()
            if session_id in self._meta:
                self._meta[session_id]['native_started'] = True
                self._meta[session_id]['updated_at'] = _now()
                self._save_meta_locked()

    def read(self, session_id: str, limit: int | None = None) -> list[dict[str, Any]]:
        path = self.path_for(session_id)
        if not path.exists():
            return []
        records = []
        try:
            lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
        except OSError:
            return []
        for line in lines:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                records.append(item)
        return records[-limit:] if limit else records

    def rename(self, session_id: str, title: str) -> None:
        with self._lock:
            self._reload_locked()
            if session_id not in self._meta:
                raise KeyError(session_id)
            self._meta[session_id]['title'] = _safe_title(title)
            self._meta[session_id]['updated_at'] = _now()
            self._save_meta_locked()

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._reload_locked()
            self._meta.pop(session_id, None)
            try:
                self.path_for(session_id).unlink()
            except FileNotFoundError:
                pass
            self._save_meta_locked()

    def revision(self) -> tuple[int, int]:
        
        try:
            stat = self.meta_path.stat()
            return stat.st_mtime_ns, stat.st_size
        except OSError:
            return 0, 0


def _now() -> str:
    return datetime.now().isoformat(timespec='seconds')


def _safe_title(value: str) -> str:
    title = ' '.join(str(value or '').split()).strip()
    return title[:80] or '新会话'
