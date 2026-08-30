import json
import os
from datetime import datetime
from pathlib import Path


class UsageLedger:


    def __init__(self, path: str | os.PathLike[str] = None):
        if path is None:
            from .runtime import runtime_dir
            path = runtime_dir() / 'usage.json'
        self.path = Path(path)
        self.data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding='utf-8'))
                if isinstance(data, dict):
                    return data
            except (OSError, json.JSONDecodeError):
                pass
        return {}

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=1),
            encoding='utf-8',
        )
        tmp.replace(self.path)

    @staticmethod
    def _month() -> str:
        return datetime.now().strftime('%Y-%m')

    def record(self, provider_id: str, chars: int):
        if chars <= 0:
            return
        month = self._month()
        entry = self.data.setdefault(provider_id, {})
        entry[month] = entry.get(month, 0) + chars
        self._save()

    def month_total(self, provider_id: str) -> int:
        return self.data.get(provider_id, {}).get(self._month(), 0)

    def monthly_history(self, provider_id: str) -> dict:
        return dict(self.data.get(provider_id, {}))
