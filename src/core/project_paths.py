from __future__ import annotations

import hashlib
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ProjectPaths:


    root: Path

    @classmethod
    def for_root(cls, root: str | os.PathLike[str]) -> 'ProjectPaths':
        return cls(Path(root).expanduser().resolve())

    @property
    def internal(self) -> Path:
        return self.root / '.workknacks'

    @property
    def state(self) -> Path:
        return self.internal / 'state'

    @property
    def index(self) -> Path:
        return self.state / 'index.json'

    @property
    def agent_config(self) -> Path:
        return self.state / 'agent.json'

    @property
    def sessions(self) -> Path:
        return self.internal / 'sessions'

    @property
    def cache(self) -> Path:
        return self.internal / 'cache'

    @property
    def metadata_cache(self) -> Path:
        return self.cache / 'metadata'

    @property
    def backups(self) -> Path:
        return self.internal / 'backups'

    @property
    def history(self) -> Path:
        return self.internal / 'history'

    @property
    def temp(self) -> Path:
        return self.internal / 'tmp'

    @property
    def agent_worktree(self) -> Path:

        return self.temp / 'agent-worktree'

    def ensure(self) -> 'ProjectPaths':


        for path in (self.state, self.sessions, self.cache, self.backups, self.temp, self.history):
            path.mkdir(parents=True, exist_ok=True)
        return self

    def cache_file(self, namespace: str, key: str, suffix: str = '.json') -> Path:
        safe_ns = ''.join(ch for ch in str(namespace) if ch.isalnum() or ch in '-_') or 'misc'
        digest = hashlib.sha256(str(key).encode('utf-8', errors='replace')).hexdigest()
        folder = self.cache / safe_ns
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f'{digest}{suffix}'

    def cleanup_cache(self, *, max_age_days: int = 30, max_bytes: int = 512 * 1024 * 1024) -> dict[str, int]:

        cache = self.cache
        if not cache.exists():
            return {'removed_files': 0, 'removed_bytes': 0, 'remaining_bytes': 0}
        now = time.time()
        max_age = max(1, int(max_age_days)) * 86400
        files: list[tuple[float, int, Path]] = []
        removed_files = 0
        removed_bytes = 0
        for path in cache.rglob('*'):
            if not path.is_file():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            if now - stat.st_mtime > max_age:
                try:
                    size = stat.st_size
                    path.unlink()
                    removed_files += 1
                    removed_bytes += size
                except OSError:
                    pass
                continue
            files.append((stat.st_mtime, stat.st_size, path))
        total = sum(item[1] for item in files)
        for _mtime, size, path in sorted(files, key=lambda item: item[0]):
            if total <= max_bytes:
                break
            try:
                path.unlink()
                total -= size
                removed_files += 1
                removed_bytes += size
            except OSError:
                pass

        for folder in sorted((p for p in cache.rglob('*') if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
            try:
                folder.rmdir()
            except OSError:
                pass
        return {'removed_files': removed_files, 'removed_bytes': removed_bytes, 'remaining_bytes': max(0, total)}

    def reset_temp(self) -> None:
        if self.temp.exists():
            shutil.rmtree(self.temp, ignore_errors=True)
        self.temp.mkdir(parents=True, exist_ok=True)
        self.temp.mkdir(parents=True, exist_ok=True)
