"""Built-in health check for the installed program.

    Jarvis.exe --selftest

Runs without opening the window, writes a plain-text report to  <Jarvis data folder>\\selftest.txt
and exits with code 0 (everything Jarvis needs works) or 1. build_installer.bat runs this right
after bundling, so a broken package is caught on the builder's PC instead of the customer's.

  PASS = fine.   WARN = Jarvis still works, but this PC may limit something (no microphone yet,
  no internet right now, ...).   FAIL = Jarvis would not work properly - the installer should
  not be shipped.
"""
import importlib
import os
import platform
import sys
import time
import traceback

import paths

_lines = []
_failed = 0


def _log(level, name, detail=""):
    _lines.append(f"[{level}] {name}" + (f" - {detail}" if detail else ""))


def _check(name, func, required=True):
    """Runs one check. func returns a short detail string, or ("WARN", message) for a soft problem."""
    global _failed
    try:
        result = func()
        if isinstance(result, tuple) and result and result[0] == "WARN":
            _log("WARN", name, result[1])
        else:
            _log("PASS", name, result or "")
    except BaseException as e:  # a check must never take the whole self-test down
        if isinstance(e, KeyboardInterrupt):
            raise
        last = (traceback.format_exc().strip().splitlines() or [repr(e)])[-1]
        if required:
            _failed += 1
            _log("FAIL", name, last)
        else:
            _log("WARN", name, last)


def _imports():
    required = [
        "config", "events", "overlay", "settings", "audio_io", "actions", "hand_mouse",
        "tools_schema", "engine", "numpy", "cv2", "mediapipe", "pyaudiowpatch", "pyttsx3",
        "psutil", "pycaw.pycaw", "comtypes", "groq", "dotenv", "pyautogui", "openwakeword",
        "onnxruntime", "tkinter", "certifi", "httpx", "screen_brightness_control",
    ]
    for module in required:
        _check(f"import {module}", lambda m=module: (importlib.import_module(m), "")[1])
    for module in ("keyboard", "PIL"):  # the app copes without these (hotkey / screenshots)
        _check(f"import {module}", lambda m=module: (importlib.import_module(m), "")[1], required=False)


def _wake_word():
    import numpy as np
    import openwakeword
    import config
    from openwakeword.model import Model
    path = openwakeword.MODELS[config.WAKE_WORD]["model_path"]
    model = Model(wakeword_models=[path])
    key = list(model.models.keys())[0]
    scores = model.predict(np.zeros(config.CHUNK_SIZE, dtype=np.int16))
    if key not in scores:
        raise RuntimeError("wake-word model returned no score")
    return f"model '{key}' loads and runs"


def _hand_tracker():
    import hand_mouse
    import mediapipe as mp
    path = next((p for p in (hand_mouse._BUNDLED_MODEL_PATH, hand_mouse._MODEL_PATH) if os.path.exists(p)), None)
    if path is None:
        return ("WARN", "hand-tracking model isn't bundled; hand mouse will download it (~8 MB) on first use")
    with open(path, "rb") as f:
        data = f.read()
    landmarker = mp.tasks.vision.HandLandmarker.create_from_options(
        mp.tasks.vision.HandLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_buffer=data),
            running_mode=mp.tasks.vision.RunningMode.VIDEO,
            num_hands=1,
        )
    )
    landmarker.close()
    return "hand tracker loads"


def _tools():
    import tools_schema
    names = [t["function"]["name"] for t in tools_schema.TOOLS_SCHEMA]
    missing = [n for n in names if n not in tools_schema.TOOL_FUNCTIONS]
    if missing:
        raise RuntimeError(f"tools without a function: {missing}")
    return f"{len(names)} PC tools registered"


def _groq_client():
    import certifi
    from groq import Groq
    Groq(api_key="selftest")  # builds the client only; no request is sent
    if not os.path.exists(certifi.where()):
        raise RuntimeError("HTTPS certificate bundle is missing")
    return "Groq client + HTTPS certificates present"


def _internet():
    import httpx
    r = httpx.get("https://api.groq.com/openai/v1/models", timeout=8)  # 401 without a key is expected
    return f"reached Groq (HTTP {r.status_code})"


def _data_dir():
    probe = paths.DATA_DIR / ".selftest_write"
    probe.write_text("ok")
    probe.unlink()
    return f"writable: {paths.DATA_DIR}"


def _window():
    import tkinter
    root = tkinter.Tk()
    root.withdraw()
    root.update()
    root.destroy()
    return "window system works"


def _icon():
    if not (paths.RESOURCE_DIR / "jarvis.ico").exists():
        raise RuntimeError("jarvis.ico is missing from the package")
    return "icon bundled"


def _microphone():
    import pyaudiowpatch as pyaudio
    pa = pyaudio.PyAudio()
    try:
        info = pa.get_default_input_device_info()
        return f"default microphone: {info.get('name')}"
    finally:
        pa.terminate()


def _voice():
    import pyttsx3
    voices = pyttsx3.init().getProperty("voices") or []
    if not voices:
        raise RuntimeError("no Windows text-to-speech voices installed")
    return f"{len(voices)} voice(s)"


def _volume():
    import actions
    level = actions._volume_interface().GetMasterVolumeLevelScalar()
    return f"system volume readable ({round(level * 100)}%)"


def run() -> int:
    global _failed
    _lines.clear()
    _failed = 0
    started = time.time()
    try:  # volume/voice need COM in single-threaded mode, exactly like the engine thread sets up
        import comtypes
        comtypes.CoInitialize()
    except Exception:
        pass

    _check("data folder", _data_dir)
    _check("window system (tkinter)", _window)
    _check("icon", _icon, required=False)
    _imports()
    _check("tool list", _tools)
    _check("Groq client", _groq_client)
    _check("wake-word model", _wake_word)
    _check("hand tracker", _hand_tracker)
    _check("microphone", _microphone, required=False)
    _check("voice (text-to-speech)", _voice, required=False)
    _check("volume control", _volume, required=False)
    _check("internet / Groq reachable", _internet, required=False)

    header = [
        "JARVIS SELF-TEST",
        f"python {platform.python_version()}  |  {platform.platform()}  |  packaged: {paths.FROZEN}",
        f"program files: {paths.RESOURCE_DIR}",
        f"data folder  : {paths.DATA_DIR}",
        "",
    ]
    warns = sum(1 for line in _lines if line.startswith("[WARN]"))
    footer = [
        "",
        f"RESULT: {'ALL REQUIRED CHECKS PASSED' if not _failed else f'{_failed} REQUIRED CHECK(S) FAILED'}"
        f"  ({warns} warning(s), {time.time() - started:.0f}s)",
    ]
    report = "\n".join(header + _lines + footer) + "\n"
    try:
        (paths.DATA_DIR / "selftest.txt").write_text(report, encoding="utf-8")
    except OSError:
        pass
    try:
        print(report)
    except Exception:
        pass
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(run())
