"""Every function in this file is a "tool" the chat model can call after hearing a command.

Each one is a plain Python function with a docstring and type hints for humans
reading the code — but unlike the old Gemini setup, Groq doesn't build its
tool schemas from these automatically. The actual schema each function is
exposed with lives in tools_schema.py, alongside the name→function lookup
table Groq's tool calls are dispatched through. Its return value (a short
string) is what gets spoken back, so keep returns short and natural.

To add a new capability: write a new function here following the same
pattern, then add a matching schema + dispatch entry in tools_schema.py.
"""
import ctypes
import logging
import os
import subprocess
import urllib.parse
import webbrowser
from ctypes import POINTER, cast
from datetime import datetime
from pathlib import Path

import psutil
import pyautogui
import screen_brightness_control as sbc
from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

import hand_mouse

logging.getLogger("screen_brightness_control").setLevel(logging.ERROR)  # harmless EDID warnings

# Common apps that aren't reliably launchable by their spoken name alone.
# Add to this dict if "open <app>" doesn't work for something you use a lot.
KNOWN_APPS = {
    "chrome": "chrome", "google chrome": "chrome",
    "edge": "msedge", "microsoft edge": "msedge",
    "firefox": "firefox",
    "word": "winword", "microsoft word": "winword",
    "excel": "excel", "microsoft excel": "excel",
    "powerpoint": "powerpnt", "microsoft powerpoint": "powerpnt",
    "notepad": "notepad",
    "calculator": "calc",
    "paint": "mspaint",
    "file explorer": "explorer", "explorer": "explorer", "files": "explorer",
    "vs code": "code", "visual studio code": "code",
    "spotify": "spotify",
    "discord": "discord",
    "outlook": "outlook",
    "task manager": "taskmgr",
    "control panel": "control",
    "settings": "ms-settings:",
    "command prompt": "cmd", "cmd": "cmd", "terminal": "wt",
}


# Characters that would let a mis-heard app name run extra shell commands.
# The installed program has no console, so every shell command would flash a black window.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_UNSAFE_CHARS = set('&|<>^%"')

# Never closed by voice, however the request is worded.
_PROTECTED_PROCESSES = {
    "system", "registry", "smss", "csrss", "wininit", "winlogon",
    "services", "lsass", "svchost", "dwm",
}


def _volume_interface():
    speakers = AudioUtilities.GetSpeakers()
    # Newer pycaw returns an AudioDevice wrapper that exposes the endpoint volume directly;
    # older versions return a raw COM device that needs Activate().
    if hasattr(speakers, "EndpointVolume"):
        return speakers.EndpointVolume
    device = getattr(speakers, "_dev", speakers)  # AudioDevice wraps the raw COM device as ._dev
    interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(interface, POINTER(IAudioEndpointVolume))


def open_app(app_name: str) -> str:
    """Opens a desktop application by name, e.g. "chrome", "notepad", "spotify", "word".

    Args:
        app_name: The application name, roughly as the user said it.
    """
    name = (app_name or "").strip()
    if not name or any(ch in _UNSAFE_CHARS for ch in name):
        return "I couldn't tell which app you meant."
    target = KNOWN_APPS.get(name.lower(), name)
    if " " in target and not target.startswith("start "):
        target = f'"{target}"'
    try:
        subprocess.Popen(f'start "" {target}', shell=True, creationflags=_NO_WINDOW)
        return f"Opening {app_name}."
    except Exception as e:
        return f"I couldn't open {app_name}: {e}"


def close_app(app_name: str) -> str:
    """Closes a running application by name, e.g. "chrome", "spotify".

    Args:
        app_name: The application/process name, roughly as the user said it.
    """
    target = (app_name or "").lower().strip()
    if len(target) < 3:
        return "That app name is too short for me to close safely."
    closed = set()
    for proc in psutil.process_iter(["name"]):
        pname = (proc.info.get("name") or "").lower()
        stem = pname[:-4] if pname.endswith(".exe") else pname
        if proc.pid == os.getpid() or stem in _PROTECTED_PROCESSES:
            continue
        if target in pname or (len(stem) >= 4 and stem in target):
            try:
                proc.terminate()
                closed.add(proc.info["name"])
            except Exception:
                pass
    if closed:
        return f"Closed {', '.join(closed)}."
    return f"Nothing running matched '{app_name}'."


def take_screenshot() -> str:
    """Takes a screenshot of the whole screen and saves it to Pictures\\Screenshots."""
    try:
        folder = Path.home() / "Pictures" / "Screenshots"
        folder.mkdir(parents=True, exist_ok=True)
        filename = folder / f"jarvis_{datetime.now():%Y%m%d_%H%M%S}.png"
        pyautogui.screenshot(str(filename))
        return f"Screenshot saved to {filename.name}."
    except Exception as e:
        return f"Couldn't take a screenshot: {e}"


def set_volume(level_percent: int) -> str:
    """Sets the system master volume to a specific percentage.

    Args:
        level_percent: Target volume from 0 (silent) to 100 (max).
    """
    level_percent = max(0, min(100, int(level_percent)))
    try:
        _volume_interface().SetMasterVolumeLevelScalar(level_percent / 100, None)
    except Exception as e:
        return f"Couldn't change the volume: {e}"
    return f"Volume set to {level_percent} percent."


def mute(should_mute: bool = True) -> str:
    """Mutes or unmutes system audio.

    Args:
        should_mute: True to mute, False to unmute.
    """
    try:
        _volume_interface().SetMute(1 if should_mute else 0, None)
    except Exception as e:
        return f"Couldn't change mute: {e}"
    return "Muted." if should_mute else "Unmuted."


def set_brightness(level_percent: int) -> str:
    """Sets the display brightness to a specific percentage. Works reliably on laptop
    built-in screens; external monitors need DDC/CI support enabled to respond to this.

    Args:
        level_percent: Target brightness from 0 (dimmest) to 100 (brightest).
    """
    level_percent = max(0, min(100, int(level_percent)))
    try:
        sbc.set_brightness(level_percent)
    except Exception as e:
        return f"Couldn't change brightness: {e}"
    return f"Brightness set to {level_percent} percent."


def start_hand_mouse() -> str:
    """Starts webcam hand-tracking mouse control: point the index finger to move the
    cursor. Pinch thumb to index finger to drag — a quick touch clicks, holding it while
    moving the hand drags. Pinch thumb to middle finger for a plain click. Call this when
    the user asks to start, turn on, or enable hand mouse / hand tracking.
    """
    return hand_mouse.controller.start()


def stop_hand_mouse() -> str:
    """Stops webcam hand-tracking mouse control. Call this when the user asks to stop, turn
    off, or disable hand mouse / hand tracking.
    """
    return hand_mouse.controller.stop()


def lock_pc() -> str:
    """Locks the PC. Fully reversible with the user's normal password/PIN — safe to call
    immediately without asking for confirmation first."""
    ctypes.windll.user32.LockWorkStation()
    return "Locked."


def shutdown_pc(delay_seconds: int = 30) -> str:
    """Schedules a shutdown after a short delay so the user has time to cancel it out loud.
    Safe to call as soon as the user asks — no need to ask for confirmation first, since the
    delay itself is the confirmation window.

    Args:
        delay_seconds: Seconds before shutdown. Defaults to 30; don't go below 10.
    """
    delay_seconds = max(10, int(delay_seconds))
    subprocess.run(["shutdown", "/s", "/t", str(delay_seconds)], shell=True, creationflags=_NO_WINDOW)
    return f"Shutting down in {delay_seconds} seconds. Say 'cancel shutdown' to stop it."


def restart_pc(delay_seconds: int = 30) -> str:
    """Schedules a restart after a short delay so the user has time to cancel it out loud.
    Safe to call as soon as the user asks — no need to ask for confirmation first, since the
    delay itself is the confirmation window.

    Args:
        delay_seconds: Seconds before restart. Defaults to 30; don't go below 10.
    """
    delay_seconds = max(10, int(delay_seconds))
    subprocess.run(["shutdown", "/r", "/t", str(delay_seconds)], shell=True, creationflags=_NO_WINDOW)
    return f"Restarting in {delay_seconds} seconds. Say 'cancel shutdown' to stop it."


def cancel_shutdown() -> str:
    """Cancels a previously scheduled shutdown or restart."""
    result = subprocess.run(["shutdown", "/a"], shell=True, capture_output=True, text=True, creationflags=_NO_WINDOW)
    if result.returncode == 0:
        return "Cancelled."
    return "There wasn't a shutdown or restart scheduled."


def search_files(query: str, search_root: str = "") -> str:
    """Searches for files whose name contains the given text, inside Desktop, Documents and
    Downloads by default.

    Args:
        query: Text to look for in file names.
        search_root: Optional specific folder to search instead of the default folders.
    """
    roots = [search_root] if search_root else [
        str(Path.home() / "Desktop"),
        str(Path.home() / "Documents"),
        str(Path.home() / "Downloads"),
    ]
    matches = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, _, filenames in os.walk(root):
            for fname in filenames:
                if query.lower() in fname.lower():
                    matches.append(os.path.join(dirpath, fname))
                    if len(matches) >= 10:
                        break
            if len(matches) >= 10:
                break
        if len(matches) >= 10:
            break

    if not matches:
        return f"No files matching '{query}' in Desktop, Documents, or Downloads."
    listing = "; ".join(os.path.basename(m) for m in matches)
    return f"Found {len(matches)} match(es): {listing}"


def open_website(url_or_query: str) -> str:
    """Opens a website in the default browser. Give it a URL, or a plain phrase to Google.

    Args:
        url_or_query: A URL like "github.com", or a search phrase like "weather in london".
    """
    text = url_or_query.strip()
    if "." in text and " " not in text:
        if not text.startswith(("http://", "https://")):
            text = "https://" + text
        webbrowser.open(text)
        return f"Opening {text}."
    webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote(text))
    return f"Searching the web for {url_or_query}."
