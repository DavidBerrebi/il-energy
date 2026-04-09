"""Israeli Energy Compliance Engine for SI 5282."""

import sys
from pathlib import Path

__version__ = "0.1.0"


def _standards_dir() -> Path:
    """Return path to standards/si5282/ — works both in dev and PyInstaller bundle."""
    # PyInstaller sets sys._MEIPASS to the temp extraction folder
    if getattr(sys, "_MEIPASS", None):
        return Path(sys._MEIPASS) / "standards" / "si5282"
    # Dev: standards/ sits at repo root, 3 levels above this __init__.py
    return Path(__file__).resolve().parent.parent.parent / "standards" / "si5282"


STANDARDS_DIR = _standards_dir()
