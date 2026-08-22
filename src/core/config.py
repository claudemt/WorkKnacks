import os
from pathlib import Path

class Config:

    def __init__(self, project_root: str = None):
        if project_root is None:
            project_root = Path(__file__).resolve().parent.parent.parent
        self.root = Path(project_root)
        self._load_env()

    def _load_env(self):

        env_path = self.root / 'config' / '.env.local'
        if env_path.exists():
            with open(env_path, encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#') or '=' not in line:
                        continue
                    key, val = line.split('=', 1)
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if val and key not in os.environ:
                        os.environ[key] = val

    def get(self, key: str, default: str = '') -> str:
        return os.environ.get(key, default)

    def get_int(self, key: str, default: int = 0) -> int:
        try:
            return int(self.get(key, str(default)))
        except ValueError:
            return default

    def get_float(self, key: str, default: float = 0.0) -> float:
        try:
            return float(self.get(key, str(default)))
        except ValueError:
            return default

    def has(self, key: str) -> bool:
        return bool(self.get(key))

    def set(self, key: str, value: str):

        os.environ[key] = value
        env_path = self.root / 'config' / '.env.local'
        lines = []
        found = False
        if env_path.exists():
            with open(env_path, encoding='utf-8') as f:
                for line in f:
                    if line.strip().startswith(key + '='):
                        lines.append(f'{key}={value}\n')
                        found = True
                    else:
                        lines.append(line)
        if not found:
            lines.append(f'{key}={value}\n')
        with open(env_path, 'w', encoding='utf-8') as f:
            f.writelines(lines)

config = Config()

