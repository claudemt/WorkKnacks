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
        self.set_many({key: value})

    def set_many(self, values: dict[str, str]):
        env_path = self.root / 'config' / '.env.local'
        env_path.parent.mkdir(parents=True, exist_ok=True)
        normalized = {str(k).strip(): str(v).strip() for k, v in values.items() if str(k).strip()}
        for key, value in normalized.items():
            if value:
                os.environ[key] = value
            else:
                os.environ.pop(key, None)

        existing = []
        seen = set()
        if env_path.exists():
            existing = env_path.read_text(encoding='utf-8').splitlines(keepends=True)
        output = []
        for line in existing:
            stripped = line.strip()
            if '=' in stripped and not stripped.startswith('#'):
                key = stripped.split('=', 1)[0].strip()
                if key in normalized:
                    output.append(f'{key}={normalized[key]}\n')
                    seen.add(key)
                    continue
            output.append(line if line.endswith('\n') else line + '\n')
        if output and output[-1].strip():
            output.append('\n')
        for key, value in normalized.items():
            if key not in seen:
                output.append(f'{key}={value}\n')
        env_path.write_text(''.join(output), encoding='utf-8')

config = Config()

