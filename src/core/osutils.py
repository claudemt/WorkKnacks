from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def open_path(path: str | Path) -> None:
    target = str(Path(path).expanduser().resolve())
    if os.name == 'nt':
        os.startfile(target)
    elif sys.platform == 'darwin':
        subprocess.Popen(['open', target])
    else:
        subprocess.Popen(['xdg-open', target])


def reveal_path(path: str | Path) -> None:
    target = Path(path).expanduser().resolve()
    if os.name == 'nt':
        subprocess.Popen(['explorer', '/select,', str(target)])
    elif sys.platform == 'darwin':
        subprocess.Popen(['open', '-R', str(target)])
    else:
        open_path(target.parent)
        open_path(target.parent)
