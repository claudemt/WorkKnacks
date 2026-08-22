import json, os, hashlib
from pathlib import Path
from .runtime import runtime_dir

class ProgressManager:

    def __init__(self, state_path: str = None, save_every: int = 10):
        if state_path is None:
            state_path = runtime_dir() / '.progress.json'
        self.state_path = Path(state_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state = self._load()
        # 大文件逐块翻译时，每块都读全文件算 hash 是 O(n²) 的，
        # 这里按 (路径, mtime, 大小) 缓存一次；落盘批量执行，崩溃最多丢 save_every 块。
        self._hash_cache = {}
        self._save_every = save_every
        self._since_save = 0

    def _load(self) -> dict:
        if self.state_path.exists():
            with open(self.state_path, encoding='utf-8') as f:
                return json.load(f)
        return {}

    def _save(self):
        with open(self.state_path, 'w', encoding='utf-8') as f:
            json.dump(self.state, f, ensure_ascii=False, separators=(',', ':'))

    def flush(self):
        if self._since_save:
            self._save()
            self._since_save = 0

    def file_hash(self, path: str) -> str:
        stat = os.stat(path)
        key = (os.path.abspath(path), stat.st_mtime_ns, stat.st_size)
        cached = self._hash_cache.get(key)
        if cached is not None:
            return cached
        with open(path, 'rb') as f:
            digest = hashlib.sha256(f.read()).hexdigest()[:16]
        self._hash_cache[key] = digest
        return digest

    def get_chunk(self, file_path: str, chunk_idx: int) -> str | None:

        fh = self.file_hash(file_path)
        return self.state.get(fh, {}).get(str(chunk_idx))

    def set_chunk(self, file_path: str, chunk_idx: int, result: str):

        fh = self.file_hash(file_path)
        if fh not in self.state:
            self.state[fh] = {}
        self.state[fh][str(chunk_idx)] = result
        self._since_save += 1
        if self._since_save >= self._save_every:
            self._save()
            self._since_save = 0

    def invalidate(self, file_path: str):

        fh = self.file_hash(file_path)
        self.state.pop(fh, None)
        self._save()
        self._since_save = 0

    def clear(self):

        self.state = {}
        self._save()
        self._since_save = 0

    def total_cached(self, file_path: str) -> int:
        fh = self.file_hash(file_path)
        return len(self.state.get(fh, {}))

