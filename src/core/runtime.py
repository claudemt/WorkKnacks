from __future__ import annotations

import os
from pathlib import Path


def runtime_dir() -> Path:
    root = Path(
        os.environ.get(
            'LOCALAPPDATA',
            str(Path.home() / 'AppData' / 'Local'),
        )
    )
    path = root / 'WorkKnacks'
    path.mkdir(parents=True, exist_ok=True)
    return path
