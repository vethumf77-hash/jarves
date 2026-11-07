# -*- mode: python ; coding: utf-8 -*-
# PyInstaller recipe: turns app.py + everything it needs into dist\Jarvis\Jarvis.exe (no console window).
# Run via build_installer.bat - you normally never touch this file.
import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas, binaries, hiddenimports = [], [], []

# Packages that carry data files / native libraries PyInstaller can't see on its own.
for pkg in ("openwakeword", "mediapipe", "onnxruntime"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# Loaded dynamically at run time, so they must be named explicitly.
for pkg in ("pyttsx3", "screen_brightness_control", "comtypes"):
    hiddenimports += collect_submodules(pkg)
hiddenimports += [
    "pyttsx3.drivers", "pyttsx3.drivers.sapi5",
    "win32com.client", "pythoncom", "pywintypes", "wmi",
]

datas += [("jarvis.ico", ".")]
if os.path.exists("hand_landmarker.task"):          # fetched by prepare_build.py
    datas += [("hand_landmarker.task", ".")]

a = Analysis(
    ["app.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Jarvis",
    icon="jarvis.ico",
    console=False,       # windowed app: no black console box
    upx=False,           # UPX often triggers antivirus false positives
)
coll = COLLECT(exe, a.binaries, a.datas, name="Jarvis", upx=False)
