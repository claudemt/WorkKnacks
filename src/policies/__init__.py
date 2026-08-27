from __future__ import annotations

from pathlib import Path

_POLICY_ROOT = Path(__file__).resolve().parent


def load_policy(name: str) -> str:
    key = ''.join(ch for ch in str(name) if ch.isalnum() or ch in '-_')
    path = _POLICY_ROOT / f'{key}.md'
    if not path.is_file():
        raise KeyError(name)
    return path.read_text(encoding='utf-8', errors='replace').strip()
