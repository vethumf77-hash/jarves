"""Where Jarvis keeps its files.

Running from source (python app.py):  everything lives next to the code, as before.
Installed Windows program (Jarvis.exe): the program files are read-only bundled resources,
so the things Jarvis writes - your API key (.env), settings.json and the logs - live in
%LOCALAPPDATA%\\Jarvis instead. That is also where the installer saves the API key the
customer types in.
"""
import os
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))

if FROZEN:
    # Bundled, read-only resources (icon, models) live inside the program folder.
    RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    _base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    DATA_DIR = Path(_base) / "Jarvis"
else:
    RESOURCE_DIR = Path(__file__).resolve().parent
    DATA_DIR = RESOURCE_DIR

try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    pass
