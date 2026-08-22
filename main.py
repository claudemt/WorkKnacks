import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOCAL_APP_DATA = Path(
    os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData' / 'Local'))
)
os.environ.setdefault(
    'PYTHONPYCACHEPREFIX',
    str(LOCAL_APP_DATA / 'WorkKnacks' / 'pycache'),
)

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.gui.app import main

if __name__ == '__main__':
    main()

