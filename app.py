"""Jarvis — the desktop app. Double-click the Jarvis shortcut (see create_shortcut.bat)
or run:  python app.py

Opens a window with the animated globe, a conversation log, and quick controls, and
starts the voice engine (engine.py) in the background: say "Hey Jarvis", press Talk,
click the globe, or just type a command. Closing the window quits Jarvis; the Mini
button shrinks it to the floating corner globe so it can keep running out of the way.
"""
import logging
import os
import sys
import time
import tkinter as tk
import webbrowser
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tkinter import messagebox, ttk

APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
import paths  # where files live: next to the code, or %LOCALAPPDATA%\Jarvis when installed

os.chdir(paths.RESOURCE_DIR)

APP_ID = "Jarvis.VoiceAssistant"

# ----------------------------------------------------------------------------------
# Look & feel
# ----------------------------------------------------------------------------------
BG = "#060a13"          # window background
PANEL = "#0b1220"       # cards
PANEL_2 = "#111a2e"     # inputs, buttons
BORDER = "#1c2a45"
TEXT = "#e6edf7"
MUTED = "#7d8aa5"
ACCENT = "#38bdf8"
GOOD = "#22c55e"
WARN = "#f97316"
BAD = "#ef4444"

FONT = "Segoe UI"
MONO = "Consolas"

STATE_LABELS = {
    "boot": ("STARTING UP", None),
    "idle": ("STANDBY", 'Say "Hey Jarvis", press Talk, or type a command'),
    "listening": ("LISTENING", "Go ahead, I'm listening..."),
    "thinking": ("THINKING", "Working on it..."),
    "speaking": ("SPEAKING", None),
    "paused": ("MIC OFF", 'Wake word is off. Press Talk or type a command'),
    "error": ("NEEDS ATTENTION", "See the conversation for details"),
}

CHAT_MODELS = ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "llama-3.3-70b-versatile"]
STT_MODELS = ["whisper-large-v3-turbo", "whisper-large-v3"]


# ----------------------------------------------------------------------------------
# Startup helpers (logging, DPI, single instance)
# ----------------------------------------------------------------------------------
def setup_logging() -> None:
    """Everything goes to jarvis.log — the app runs without a console window, so this is
    where to look if something misbehaves."""
    log_path = paths.DATA_DIR / "jarvis.log"
    handler = RotatingFileHandler(log_path, maxBytes=512_000, backupCount=2, encoding="utf-8")
    logging.basicConfig(
        level=logging.INFO, handlers=[handler],
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # pythonw.exe has no console, so print() / library warnings would have nowhere to go.
    if sys.stdout is None or sys.stderr is None:
        console_log = paths.DATA_DIR / "jarvis.console.log"
        mode = "w" if console_log.exists() and console_log.stat().st_size > 1_000_000 else "a"  # keep it small
        stream = open(console_log, mode, encoding="utf-8", buffering=1)
        if sys.stdout is None:
            sys.stdout = stream
        if sys.stderr is None:
            sys.stderr = stream

    for _stream in (sys.stdout, sys.stderr):  # an emoji in a reply must never crash a print()
        try:
            _stream.reconfigure(errors="replace")
        except Exception:
            pass

    def _log_uncaught(exc_type, exc, tb):
        logging.getLogger("jarvis").critical("Uncaught exception", exc_info=(exc_type, exc, tb))

    sys.excepthook = _log_uncaught
    try:
        import threading
        threading.excepthook = lambda a: logging.getLogger("jarvis").critical(
            "Uncaught exception in thread %s", a.thread.name if a.thread else "?",
            exc_info=(a.exc_type, a.exc_value, a.exc_traceback))
    except Exception:
        pass


def prepare_windows() -> None:
    """Crisp text on high-DPI screens, and its own taskbar identity/icon (not 'python')."""
    if os.name != "nt":
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


def already_running() -> bool:
    """True if another Jarvis window is already open (two copies would fight over the mic)."""
    if os.name != "nt":
        return False
    import ctypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    k32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    already_running._handle = k32.CreateMutexW(None, False, "Local\\JarvisVoiceAssistantSingleton")
    return ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS


# ----------------------------------------------------------------------------------
# Small widgets
# ----------------------------------------------------------------------------------
class FlatButton(tk.Label):
    """A flat, dark button with hover + "on" states (a plain tk.Label wired up like a button)."""

    def __init__(self, master, text, command=None, *, primary=False, small=False, **kw):
        self._primary = primary
        self._command = command
        self._active = False
        self._enabled = True
        self._hover = False
        font = (FONT, 9 if small else 10, "bold" if primary else "normal")
        super().__init__(
            master, text=text, font=font, cursor="hand2",
            padx=10 if small else 14, pady=4 if small else 7,
            highlightthickness=1, bd=0, **kw,
        )
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<ButtonRelease-1>", self._clicked)
        self._paint()

    def _set_hover(self, value):
        self._hover = value
        self._paint()

    def _clicked(self, event):
        if not self._enabled or self._command is None:
            return
        if 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height():
            self._command()

    def _paint(self):
        if not self._enabled:
            bg, fg, edge = PANEL, "#47536b", BORDER
        elif self._primary:
            bg, fg, edge = ("#7dd3fc" if self._hover else ACCENT), "#04101c", ACCENT
        elif self._active:
            bg, fg, edge = ("#16406a" if self._hover else "#12345a"), "#bfe6ff", ACCENT
        else:
            bg, fg, edge = ("#18243d" if self._hover else PANEL_2), TEXT, BORDER
        self.configure(bg=bg, fg=fg, highlightbackground=edge, highlightcolor=edge)

    def set_active(self, value: bool):
        self._active = value
        self._paint()

    def set_enabled(self, value: bool):
        self._enabled = value
        self.configure(cursor="hand2" if value else "arrow")
        self._paint()

    def set_text(self, text: str):
        self.configure(text=text)


class FlatSlider(tk.Canvas):
    """A slider drawn by hand (tk.Scale can't be themed properly on Windows — its handle
    disappears into a dark background). Click or drag anywhere on it; arrow keys work when
    focused. command(value) fires while moving, release(value) once you let go."""

    def __init__(self, master, from_, to, value, resolution=1, command=None, release=None,
                 bg=PANEL, height=24, pad=10):
        super().__init__(master, height=height, bg=bg, highlightthickness=0, bd=0,
                         cursor="hand2", takefocus=1)
        self.from_, self.to, self.resolution = from_, to, resolution
        self._value = value
        self._command, self._release = command, release
        self._pad = pad
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<ButtonPress-1>", self._mouse)
        self.bind("<B1-Motion>", self._mouse)
        self.bind("<ButtonRelease-1>", lambda e: self._release and self._release(self._value))
        for key, direction in (("Left", -1), ("Down", -1), ("Right", 1), ("Up", 1)):
            self.bind(f"<KeyPress-{key}>", lambda e, d=direction: self._nudge(d))
            self.bind(f"<KeyRelease-{key}>", lambda e: self._release and self._release(self._value))

    def get(self):
        return self._value

    def set(self, value):
        """Moves the handle without firing any callback."""
        self._value = max(self.from_, min(self.to, value))
        self._draw()

    def _snap(self, value):
        value = round(value / self.resolution) * self.resolution
        value = max(self.from_, min(self.to, value))
        return int(value) if float(self.resolution).is_integer() else round(value, 3)

    def _mouse(self, event):
        self.focus_set()
        span = max(1, self.winfo_width() - 2 * self._pad)
        ratio = max(0.0, min(1.0, (event.x - self._pad) / span))
        self._move_to(self._snap(self.from_ + ratio * (self.to - self.from_)))

    def _nudge(self, direction):
        step = self.resolution if self.resolution >= 1 else self.resolution
        step = step * (5 if float(self.resolution).is_integer() else 1)
        self._move_to(self._snap(self._value + direction * step))

    def _move_to(self, value):
        if value != self._value:
            self._value = value
            self._draw()
            if self._command:
                self._command(value)

    def _draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 20:
            return
        pad, mid = self._pad, h / 2
        ratio = (self._value - self.from_) / ((self.to - self.from_) or 1)
        x = pad + ratio * (w - 2 * pad)
        self.create_line(pad, mid, w - pad, mid, fill="#1c2a45", width=4, capstyle="round")
        if x > pad:
            self.create_line(pad, mid, x, mid, fill=ACCENT, width=4, capstyle="round")
        r = 7
        self.create_oval(x - r, mid - r, x + r, mid + r, fill=TEXT, outline=ACCENT, width=2)


def attach_edit_menu(entry: tk.Entry) -> None:
    """Right-click Cut / Copy / Paste on a text box (Tk has no such menu by default, and many
    people paste with the mouse instead of Ctrl+V)."""
    menu = tk.Menu(entry, tearoff=0, bg=PANEL_2, fg=TEXT, activebackground=ACCENT,
                   activeforeground="#04101c", bd=0)
    menu.add_command(label="Cut", command=lambda: entry.event_generate("<<Cut>>"))
    menu.add_command(label="Copy", command=lambda: entry.event_generate("<<Copy>>"))
    menu.add_command(label="Paste", command=lambda: entry.event_generate("<<Paste>>"))
    menu.add_separator()
    menu.add_command(label="Select all", command=lambda: (entry.select_range(0, "end"), entry.icursor("end")))

    def popup(event):
        entry.focus_set()
        menu.tk_popup(event.x_root, event.y_root)

    entry.bind("<Button-3>", popup)


def make_card(master, **pack):
    frame = tk.Frame(master, bg=PANEL, highlightthickness=1, highlightbackground=BORDER, bd=0)
    return frame


# ----------------------------------------------------------------------------------
# Mini mode: the little floating globe
# ----------------------------------------------------------------------------------
class MiniGlobe(tk.Toplevel):
    SIZE = 150
    TRANSPARENT = "#010101"

    def __init__(self, app: "JarvisApp"):
        super().__init__(app.root)
        from overlay import GlobeRenderer
        self.app = app
        self.size = app.s(self.SIZE)
        self.withdraw()
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg=self.TRANSPARENT)
        try:
            self.attributes("-transparentcolor", self.TRANSPARENT)  # Windows-only
        except tk.TclError:
            pass
        x = self.winfo_screenwidth() - self.size - app.s(24)
        y = self.winfo_screenheight() - self.size - app.s(64)  # clear of the taskbar
        self.geometry(f"{self.size}x{self.size}+{x}+{y}")

        self.canvas = tk.Canvas(self, width=self.size, height=self.size, bg=self.TRANSPARENT,
                                highlightthickness=0, cursor="fleur")
        self.canvas.pack()
        self.renderer = GlobeRenderer(self.canvas, self.size)

        self.menu = tk.Menu(self, tearoff=0, bg=PANEL_2, fg=TEXT, activebackground=ACCENT,
                            activeforeground="#04101c", bd=0)
        self.menu.add_command(label="Open Jarvis", command=app.leave_mini)
        self.menu.add_command(label="Talk now", command=app.talk)
        self.menu.add_separator()
        self.menu.add_command(label="Quit", command=app.quit)

        self._drag = (0, 0)
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._move)
        self.canvas.bind("<Double-Button-1>", lambda e: app.leave_mini())
        self.canvas.bind("<Button-3>", lambda e: self.menu.tk_popup(e.x_root, e.y_root))

    def _press(self, event):
        self._drag = (event.x_root - self.winfo_x(), event.y_root - self.winfo_y())

    def _move(self, event):
        self.geometry(f"+{event.x_root - self._drag[0]}+{event.y_root - self._drag[1]}")


# ----------------------------------------------------------------------------------
# Settings window
# ----------------------------------------------------------------------------------
class SettingsDialog(tk.Toplevel):
    def __init__(self, app: "JarvisApp", reason: str = ""):
        super().__init__(app.root)
        import settings
        self.app = app
        self.settings = settings
        self.title("Jarvis settings")
        self.configure(bg=PANEL, padx=app.s(22), pady=app.s(18))
        self.resizable(False, False)
        self.transient(app.root)

        cur = settings.current()
        row = 0

        if reason:
            tk.Label(self, text=reason, bg=PANEL, fg=WARN, font=(FONT, 10), justify="left",
                     wraplength=app.s(430)).grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 10))
            row += 1

        def label(text, r, hint=None):
            tk.Label(self, text=text, bg=PANEL, fg=TEXT, font=(FONT, 10)).grid(
                row=r, column=0, sticky="w", pady=(8, 0), padx=(0, 14))
            if hint:
                tk.Label(self, text=hint, bg=PANEL, fg=MUTED, font=(FONT, 8)).grid(
                    row=r + 1, column=1, columnspan=2, sticky="w")

        def entry(var, show=None, width=34):
            box = tk.Entry(self, textvariable=var, show=show, width=width, bg=PANEL_2, fg=TEXT,
                           insertbackground=TEXT, relief="flat", font=(FONT, 10),
                           highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT)
            attach_edit_menu(box)
            return box

        # API key
        self.key_var = tk.StringVar(value=settings.get_api_key())
        label("Groq API key", row)
        self.key_entry = entry(self.key_var, show="•")
        self.key_entry.grid(row=row, column=1, sticky="we", pady=(8, 0), ipady=4)
        key_buttons = tk.Frame(self, bg=PANEL)
        key_buttons.grid(row=row, column=2, padx=(6, 0), pady=(8, 0))
        FlatButton(key_buttons, "Paste", self._paste_key, small=True).pack(side="left", padx=(0, 4))
        self.show_btn = FlatButton(key_buttons, "Show", self._toggle_key, small=True)
        self.show_btn.pack(side="left")
        row += 1
        link = tk.Label(self, text="Get a free key at console.groq.com/keys", bg=PANEL, fg=ACCENT,
                        font=(FONT, 8, "underline"), cursor="hand2")
        link.grid(row=row, column=1, columnspan=2, sticky="w")
        link.bind("<Button-1>", lambda e: webbrowser.open("https://console.groq.com/keys"))
        row += 1

        # models
        self.chat_var = tk.StringVar(value=cur["GROQ_CHAT_MODEL"])
        label("Chat model", row)
        ttk.Combobox(self, textvariable=self.chat_var, values=CHAT_MODELS, width=32).grid(
            row=row, column=1, columnspan=2, sticky="we", pady=(8, 0))
        row += 1
        self.stt_var = tk.StringVar(value=cur["GROQ_STT_MODEL"])
        label("Speech-to-text model", row)
        ttk.Combobox(self, textvariable=self.stt_var, values=STT_MODELS, width=32).grid(
            row=row, column=1, columnspan=2, sticky="we", pady=(8, 0))
        row += 1

        # sliders
        self.thr_value = cur["WAKE_WORD_THRESHOLD"]
        label("Wake-word threshold", row, "Lower = reacts to \"Hey Jarvis\" more easily (more false triggers)")
        self._slider_row(row, 0.2, 0.9, 0.05, self.thr_value, "thr")
        row += 2
        self.sil_value = cur["SILENCE_SECONDS"]
        label("Stop recording after", row, "Seconds of silence that mean you've finished talking")
        self._slider_row(row, 0.5, 3.0, 0.1, self.sil_value, "sil")
        row += 2

        # hotkey
        self.hot_var = tk.StringVar(value=cur["HAND_MOUSE_HOTKEY"])
        label("Hand-mouse hotkey", row, "Works anywhere in Windows, e.g. ctrl+alt+h or f9")
        entry(self.hot_var, width=20).grid(row=row, column=1, sticky="w", pady=(8, 0), ipady=4)
        row += 2

        # checkboxes
        self.speak_var = tk.BooleanVar(value=bool(cur["SPEAK_REPLIES"]))
        self.debug_var = tk.BooleanVar(value=bool(cur["HAND_MOUSE_DEBUG_WINDOW"]))
        for text, var in (("Read Jarvis's replies out loud", self.speak_var),
                          ("Show the camera preview window while hand mouse runs", self.debug_var)):
            tk.Checkbutton(self, text=text, variable=var, bg=PANEL, fg=TEXT, selectcolor=PANEL_2,
                           activebackground=PANEL, activeforeground=TEXT, font=(FONT, 10),
                           highlightthickness=0, bd=0).grid(row=row, column=0, columnspan=3, sticky="w", pady=(10, 0))
            row += 1

        # buttons
        buttons = tk.Frame(self, bg=PANEL)
        buttons.grid(row=row, column=0, columnspan=3, sticky="e", pady=(18, 0))
        FlatButton(buttons, "Cancel", self.destroy).pack(side="left", padx=(0, 8))
        FlatButton(buttons, "Save", self._save, primary=True).pack(side="left")

        self.columnconfigure(1, weight=1)
        self.update_idletasks()
        x = app.root.winfo_rootx() + (app.root.winfo_width() - self.winfo_width()) // 2
        y = app.root.winfo_rooty() + (app.root.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        self.grab_set()
        self.key_entry.focus_set()
        self.bind("<Escape>", lambda e: self.destroy())

    def _slider_row(self, row, low, high, step, value, name):
        holder = tk.Frame(self, bg=PANEL)
        holder.grid(row=row, column=1, columnspan=2, sticky="we", pady=(8, 0))
        readout = tk.Label(holder, text=f"{value:g}", bg=PANEL, fg=TEXT, font=(FONT, 10), width=5, anchor="e")
        readout.pack(side="right")

        def changed(v):
            setattr(self, f"{name}_value", v)
            readout.configure(text=f"{v:g}")

        slider = FlatSlider(holder, low, high, value, resolution=step, command=changed, pad=self.app.s(8),
                            height=self.app.s(26))
        slider.pack(side="left", fill="x", expand=True)

    def _paste_key(self):
        """Fills the key box from the clipboard - one click, no keyboard shortcuts needed."""
        try:
            text = self.clipboard_get().strip()
        except tk.TclError:  # clipboard empty or not text
            return
        if text:
            self.key_var.set(text)
            self.key_entry.icursor("end")

    def _toggle_key(self):
        hidden = self.key_entry.cget("show") != ""
        self.key_entry.configure(show="" if hidden else "•")
        self.show_btn.set_text("Hide" if hidden else "Show")

    def _save(self):
        hotkey = self.hot_var.get().strip().lower()
        if not hotkey:
            messagebox.showerror("Jarvis", "The hand-mouse hotkey can't be empty.", parent=self)
            return
        key = self.key_var.get().strip()
        if key and not key.startswith("gsk_"):
            if not messagebox.askyesno(
                    "Jarvis", "Groq keys normally start with \"gsk_\". Save this one anyway?", parent=self):
                return
        old_hotkey = self.settings.current()["HAND_MOUSE_HOTKEY"]
        self.settings.save({
            "GROQ_CHAT_MODEL": self.chat_var.get().strip() or CHAT_MODELS[0],
            "GROQ_STT_MODEL": self.stt_var.get().strip() or STT_MODELS[0],
            "WAKE_WORD_THRESHOLD": round(float(self.thr_value), 2),
            "SILENCE_SECONDS": round(float(self.sil_value), 1),
            "HAND_MOUSE_HOTKEY": hotkey,
            "HAND_MOUSE_DEBUG_WINDOW": self.debug_var.get(),
            "SPEAK_REPLIES": self.speak_var.get(),
        })
        if key:
            self.settings.save_api_key(key)
            self.app.engine.set_api_key(key)
        if hotkey != old_hotkey:
            error = self.app.bind_hotkey(hotkey)
            if error:
                messagebox.showerror("Jarvis", f"Couldn't use that hotkey:\n{error}", parent=self)
                self.settings.save({"HAND_MOUSE_HOTKEY": old_hotkey})
                self.app.bind_hotkey(old_hotkey)
                return
        self.app.refresh_labels()
        self.app.log_line("system", "Settings saved.")
        self.destroy()


# ----------------------------------------------------------------------------------
# The main window
# ----------------------------------------------------------------------------------
class JarvisApp:
    def __init__(self, root: tk.Tk, engine=None, start_engine: bool = True):
        import events
        import settings
        from overlay import GlobeRenderer, overlay
        from engine import JarvisEngine

        self.root = root
        self.events = events
        self.settings = settings
        self.overlay = overlay
        self.engine = engine or JarvisEngine()
        self.ui_scale = max(1.0, root.winfo_fpixels("1i") / 96.0)

        self._hotkey_handle = None
        self._muted = False
        self._fatal = False
        self._mini = None
        self._last_state = None
        self._last_hand = None
        self._last_hotkey = 0.0

        events.enable()
        self._style_ttk()
        self._build(GlobeRenderer)
        self.refresh_labels()

        self.log_line("system", 'Starting up. Once the globe turns blue, say "Hey Jarvis" or type below.')
        error = self.bind_hotkey(settings.current()["HAND_MOUSE_HOTKEY"])
        if error:
            self.log_line("error", f"Hand-mouse hotkey unavailable: {error}")

        root.protocol("WM_DELETE_WINDOW", self.quit)
        if start_engine:
            self.engine.start()
        self.root.after(33, self._tick)

    # --- sizing ---

    def s(self, px: float) -> int:
        return int(round(px * self.ui_scale))

    # --- construction ---

    def _style_ttk(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Jarvis.Vertical.TScrollbar", background=PANEL_2, troughcolor=PANEL,
                        bordercolor=PANEL, arrowcolor=MUTED, lightcolor=PANEL_2, darkcolor=PANEL_2,
                        relief="flat")
        style.map("Jarvis.Vertical.TScrollbar", background=[("active", BORDER)])
        style.configure("TCombobox", fieldbackground=PANEL_2, background=PANEL_2, foreground=TEXT,
                        arrowcolor=MUTED, bordercolor=BORDER, lightcolor=PANEL_2, darkcolor=PANEL_2,
                        selectbackground=PANEL_2, selectforeground=TEXT)
        style.map("TCombobox", fieldbackground=[("readonly", PANEL_2)], foreground=[("readonly", TEXT)])
        self.root.option_add("*TCombobox*Listbox.background", PANEL_2)
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#04101c")

    def _build(self, GlobeRenderer):
        root, s = self.root, self.s
        root.title("Jarvis")
        root.configure(bg=BG)
        root.geometry(f"{s(1040)}x{s(700)}")
        root.minsize(s(920), s(620))
        ico = paths.RESOURCE_DIR / "jarvis.ico"
        if ico.exists():
            try:
                root.iconbitmap(default=str(ico))
            except tk.TclError:
                pass

        root.columnconfigure(1, weight=1)
        root.rowconfigure(1, weight=1)

        # ---- header ----
        header = tk.Frame(root, bg=BG)
        header.grid(row=0, column=0, columnspan=2, sticky="we", padx=s(20), pady=(s(14), s(8)))
        tk.Label(header, text="J.A.R.V.I.S", bg=BG, fg=TEXT, font=(FONT, 17, "bold")).pack(side="left")
        tk.Label(header, text="  voice assistant for your PC", bg=BG, fg=MUTED, font=(FONT, 10)).pack(
            side="left", pady=(s(6), 0))
        FlatButton(header, "Settings", self.open_settings, small=True).pack(side="right")
        FlatButton(header, "Mini", self.enter_mini, small=True).pack(side="right", padx=(0, s(8)))
        self.chip = tk.Label(header, text="●  STARTING", bg=BG, fg=ACCENT, font=(FONT, 9, "bold"), cursor="arrow")
        self.chip.pack(side="right", padx=(0, s(16)))
        self.chip.bind("<Button-1>", lambda e: self._retry_engine())

        # ---- left column: globe + controls ----
        left = tk.Frame(root, bg=BG, width=s(350))
        left.pack_propagate(False)  # keep the column a steady width whatever the buttons say
        left.grid(row=1, column=0, sticky="ns", padx=(s(20), s(10)), pady=(0, s(10)))

        globe_card = make_card(left)
        globe_card.pack(fill="x")
        gsize = s(300)
        self.globe_canvas = tk.Canvas(globe_card, width=gsize, height=gsize, bg=PANEL,
                                      highlightthickness=0, cursor="hand2")
        self.globe_canvas.pack(padx=s(8), pady=(s(8), 0))
        self.globe = GlobeRenderer(self.globe_canvas, gsize, hud=True, num_points=140)
        self.globe_canvas.bind("<Button-1>", lambda e: self.talk())

        self.status_title = tk.Label(globe_card, text="STARTING UP", bg=PANEL, fg=ACCENT, font=(FONT, 15, "bold"))
        self.status_title.pack(pady=(s(2), 0))
        self.status_hint = tk.Label(globe_card, text="", bg=PANEL, fg=MUTED, font=(FONT, 9),
                                    wraplength=s(290), justify="center")
        self.status_hint.pack(pady=(s(2), s(10)), padx=s(8))

        row = tk.Frame(globe_card, bg=PANEL)
        row.pack(fill="x", padx=s(14), pady=(0, s(14)))
        row.columnconfigure((0, 1), weight=1, uniform="a")
        self.talk_btn = FlatButton(row, "Talk", self.talk, primary=True)
        self.talk_btn.grid(row=0, column=0, sticky="we", padx=(0, s(5)))
        self.listen_btn = FlatButton(row, "Wake word: ON", self.toggle_listening)
        self.listen_btn.grid(row=0, column=1, sticky="we", padx=(s(5), 0))
        self.listen_btn.set_active(True)

        controls = make_card(left)
        controls.pack(fill="x", pady=(s(10), 0))
        tk.Label(controls, text="QUICK CONTROLS", bg=PANEL, fg=MUTED, font=(FONT, 8, "bold")).pack(
            anchor="w", padx=s(14), pady=(s(10), s(2)))

        self.volume_label = tk.Label(controls, text="Volume  50%", bg=PANEL, fg=TEXT, font=(FONT, 9))
        self.volume_label.pack(anchor="w", padx=s(14))
        vrow = tk.Frame(controls, bg=PANEL)
        vrow.pack(fill="x", padx=s(14), pady=(0, s(4)))
        self.volume_scale = FlatSlider(vrow, 0, 100, 50, command=self._volume_dragged,
                                       release=self._volume_released, pad=s(8), height=s(26))
        self.volume_scale.pack(side="left", fill="x", expand=True)
        self.mute_btn = FlatButton(vrow, "Mute", self.toggle_mute, small=True, width=7)
        self.mute_btn.pack(side="left", padx=(s(8), 0))

        self.bright_label = tk.Label(controls, text="Brightness  60%", bg=PANEL, fg=TEXT, font=(FONT, 9))
        self.bright_label.pack(anchor="w", padx=s(14))
        brow = tk.Frame(controls, bg=PANEL)
        brow.pack(fill="x", padx=s(14), pady=(0, s(8)))
        self.bright_scale = FlatSlider(brow, 0, 100, 60, command=self._bright_dragged,
                                       release=self._bright_released, pad=s(8), height=s(26))
        self.bright_scale.pack(side="left", fill="x", expand=True)

        brow2 = tk.Frame(controls, bg=PANEL)
        brow2.pack(fill="x", padx=s(14), pady=(0, s(14)))
        brow2.columnconfigure((0, 1, 2), weight=1, uniform="b")
        FlatButton(brow2, "Screenshot", lambda: self.engine.run_tool("take_screenshot"), small=True).grid(
            row=0, column=0, sticky="we", padx=(0, s(4)))
        FlatButton(brow2, "Lock PC", lambda: self.engine.run_tool("lock_pc"), small=True).grid(
            row=0, column=1, sticky="we", padx=s(4))
        self.hand_btn = FlatButton(brow2, "Hand mouse", self.toggle_hand_mouse, small=True)
        self.hand_btn.grid(row=0, column=2, sticky="we", padx=(s(4), 0))

        # ---- right column: conversation ----
        right = make_card(root)
        right.grid(row=1, column=1, sticky="nsew", padx=(s(10), s(20)), pady=(0, s(10)))
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        top = tk.Frame(right, bg=PANEL)
        top.grid(row=0, column=0, columnspan=2, sticky="we", padx=s(14), pady=(s(10), s(6)))
        tk.Label(top, text="CONVERSATION", bg=PANEL, fg=MUTED, font=(FONT, 8, "bold")).pack(side="left")
        FlatButton(top, "Clear", self.clear_log, small=True).pack(side="right")
        self.voice_btn = FlatButton(top, "Voice replies: ON", self.toggle_voice, small=True)
        self.voice_btn.pack(side="right", padx=(0, s(8)))

        self.log = tk.Text(right, bg=PANEL, fg=TEXT, relief="flat", bd=0, wrap="word", cursor="arrow",
                           font=(FONT, 11), padx=s(14), pady=s(4), highlightthickness=0,
                           insertbackground=PANEL, state="disabled", spacing1=s(1), spacing3=s(1))
        self.log.grid(row=1, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(right, orient="vertical", command=self.log.yview, style="Jarvis.Vertical.TScrollbar")
        scroll.grid(row=1, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scroll.set)
        self.log.bind("<Button-1>", lambda e: self.log.focus_set())  # lets you select + Ctrl+C text
        self.log.tag_configure("meta", foreground=MUTED, font=(FONT, 8, "bold"), spacing1=s(10))
        self.log.tag_configure("user", foreground=TEXT, lmargin1=s(10), lmargin2=s(10))
        self.log.tag_configure("jarvis", foreground="#7dd3fc", lmargin1=s(10), lmargin2=s(10))
        self.log.tag_configure("tool", foreground=WARN, font=(MONO, 9), lmargin1=s(10), lmargin2=s(24), spacing1=s(3))
        self.log.tag_configure("error", foreground=BAD, font=(FONT, 10), lmargin1=s(10), lmargin2=s(10), spacing1=s(6))
        self.log.tag_configure("system", foreground=MUTED, font=(FONT, 10, "italic"), lmargin1=s(10), lmargin2=s(10), spacing1=s(6))

        entry_row = tk.Frame(right, bg=PANEL)
        entry_row.grid(row=2, column=0, columnspan=2, sticky="we", padx=s(14), pady=(s(8), s(14)))
        entry_row.columnconfigure(0, weight=1)
        self.entry = tk.Entry(entry_row, bg=PANEL_2, fg=MUTED, insertbackground=TEXT, relief="flat",
                              font=(FONT, 11), highlightthickness=1, highlightbackground=BORDER,
                              highlightcolor=ACCENT)
        self.entry.grid(row=0, column=0, sticky="we", ipady=s(7))
        attach_edit_menu(self.entry)
        self._placeholder = "Type a command, e.g. open notepad  (Enter to send)"
        self._show_placeholder()
        self.entry.bind("<FocusIn>", self._hide_placeholder)
        self.entry.bind("<FocusOut>", lambda e: self._show_placeholder())
        self.entry.bind("<Return>", lambda e: self.send_typed())
        FlatButton(entry_row, "Send", self.send_typed, primary=True).grid(row=0, column=1, padx=(s(8), 0))

        # ---- footer ----
        self.footer = tk.Label(root, text="", bg=BG, fg=MUTED, font=(FONT, 8), anchor="w")
        self.footer.grid(row=2, column=0, columnspan=2, sticky="we", padx=s(22), pady=(0, s(10)))

    # --- placeholder text in the entry box ---

    def _show_placeholder(self):
        if not self.entry.get():
            self.entry.insert(0, self._placeholder)
            self.entry.configure(fg=MUTED)

    def _hide_placeholder(self, _event=None):
        if self.entry.get() == self._placeholder and str(self.entry.cget("fg")) == MUTED:
            self.entry.delete(0, "end")
        self.entry.configure(fg=TEXT)

    # ------------------------------------------------------------------
    # Actions (buttons)
    # ------------------------------------------------------------------

    def talk(self):
        if not self.engine.ready:
            return
        state, _ = self.overlay.snapshot()
        if state in ("idle", "paused"):
            self.engine.talk_now()

    def toggle_listening(self):
        on = not self.engine.listening
        self.engine.set_listening(on)
        self.listen_btn.set_text(f"Wake word: {'ON' if on else 'OFF'}")
        self.listen_btn.set_active(on)

    def toggle_voice(self):
        import config
        on = not getattr(config, "SPEAK_REPLIES", True)
        self.settings.save({"SPEAK_REPLIES": on})
        self.refresh_labels()

    def toggle_mute(self):
        self.engine.run_tool("mute", {"should_mute": not self._muted})

    def toggle_hand_mouse(self):
        self.engine.toggle_hand_mouse()

    def _volume_dragged(self, value):
        self.volume_label.configure(text=f"Volume  {int(value)}%")

    def _volume_released(self, value):
        self.engine.run_tool("set_volume", {"level_percent": int(value)})

    def _bright_dragged(self, value):
        self.bright_label.configure(text=f"Brightness  {int(value)}%")

    def _bright_released(self, value):
        self.engine.run_tool("set_brightness", {"level_percent": int(value)})

    def send_typed(self):
        text = self.entry.get().strip()
        if not text or text == self._placeholder:
            return
        self.entry.delete(0, "end")
        self.engine.send_text(text)

    def clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.engine.reset_conversation()
        self.log_line("system", "Conversation cleared.")

    def open_settings(self, reason: str = ""):
        existing = getattr(self, "_settings_win", None)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            return
        self._settings_win = SettingsDialog(self, reason)

    def enter_mini(self):
        if self._mini is None:
            self._mini = MiniGlobe(self)
        self.root.withdraw()
        self._mini.deiconify()
        self._mini.lift()

    def leave_mini(self):
        if self._mini is not None:
            self._mini.withdraw()
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _retry_engine(self):
        if self._fatal and not self.engine.is_alive():
            self._fatal = False
            self.log_line("system", "Trying to start again...")
            self.engine.start()

    def quit(self):
        try:
            self.engine.stop(timeout=2.5)
        except Exception:
            pass
        try:
            import keyboard
            keyboard.unhook_all_hotkeys()
        except Exception:
            pass
        self.overlay.close()
        try:
            self.root.destroy()
        finally:
            logging.shutdown()
            os._exit(0)  # don't let any lingering helper thread keep the process alive

    # ------------------------------------------------------------------
    # Hotkey
    # ------------------------------------------------------------------

    def bind_hotkey(self, hotkey: str):
        """(Re)registers the global hand-mouse hotkey. Returns an error string, or None."""
        try:
            import keyboard
            if self._hotkey_handle is not None:
                try:
                    keyboard.remove_hotkey(self._hotkey_handle)
                except Exception:
                    pass
                self._hotkey_handle = None
            # The hotkey fires on keyboard's own thread — just queue an event for the window.
            self._hotkey_handle = keyboard.add_hotkey(hotkey, lambda: self.events.emit("hotkey"))
            return None
        except Exception as e:
            logging.getLogger("jarvis").warning("Hotkey %r failed: %s", hotkey, e)
            return str(e)

    # ------------------------------------------------------------------
    # Conversation log
    # ------------------------------------------------------------------

    def log_line(self, kind: str, text: str):
        stamp = datetime.now().strftime("%H:%M")
        log = self.log
        at_bottom = log.yview()[1] >= 0.98
        log.configure(state="normal")
        if kind == "user":
            log.insert("end", f"\nYOU  ·  {stamp}\n", "meta")
            log.insert("end", text + "\n", "user")
        elif kind == "jarvis":
            log.insert("end", f"\nJARVIS  ·  {stamp}\n", "meta")
            log.insert("end", text + "\n", "jarvis")
        elif kind == "tool":
            log.insert("end", "▸ " + text + "\n", "tool")
        elif kind == "error":
            log.insert("end", "⚠ " + text + "\n", "error")
        else:
            log.insert("end", text + "\n", "system")
        log.configure(state="disabled")
        if at_bottom or kind in ("user", "jarvis"):
            log.see("end")

    # ------------------------------------------------------------------
    # The 30fps heartbeat: events in, globe + labels out
    # ------------------------------------------------------------------

    def _tick(self):
        try:
            for event in self.events.drain():
                self._handle_event(event)
            self._update_visuals()
        except Exception:
            logging.getLogger("jarvis").exception("UI tick failed")
        self.root.after(33, self._tick)

    def _handle_event(self, ev: dict):
        kind = ev["type"]
        if kind == "boot":
            self.status_hint.configure(text=ev["text"])
        elif kind == "ready":
            self.log_line("system", 'Jarvis is online. Say "Hey Jarvis", press Talk, or type below.')
            self.engine.refresh_levels()
        elif kind == "fatal":
            self._fatal = True
            self.log_line("error", f"Jarvis couldn't start: {ev['text']}")
            self.log_line("system", "Details are in jarvis.log. Click the red status at the top to try again.")
        elif kind == "user":
            self.log_line("user", ev["text"])
        elif kind == "jarvis":
            self.log_line("jarvis", ev["text"])
        elif kind == "system":
            self.log_line("system", ev["text"])
        elif kind == "error":
            self.log_line("error", ev["text"])
        elif kind == "tool":
            args = ", ".join(f"{k}={v!r}" for k, v in (ev.get("args") or {}).items())
            self.log_line("tool", f"{ev['name']}({args})  →  {ev['result']}")
        elif kind == "levels":
            self._apply_levels(ev.get("volume"), ev.get("muted"))
        elif kind == "hotkey":
            now = time.monotonic()
            if now - self._last_hotkey > 0.7:  # a held / bouncing key can fire several times: ignore the burst
                self._last_hotkey = now
                self.toggle_hand_mouse()
        elif kind == "need_key":
            self.log_line("error", NO_KEY_TEXT)
            self.root.after(300, lambda: self.open_settings("Jarvis needs a Groq API key to understand and answer you."))

    def _apply_levels(self, volume, muted):
        if volume is not None:
            self.volume_scale.set(volume)
            self.volume_label.configure(text=f"Volume  {volume}%")
        if muted is not None:
            self._muted = muted
            self.mute_btn.set_text("Unmute" if muted else "Mute")
            self.mute_btn.set_active(muted)

    def _update_visuals(self):
        state, level = self.overlay.snapshot()
        if self._fatal:
            state = "error"
        elif not self.engine.ready and state not in ("error",):
            state = "boot"

        # globe (only draw the one that's visible)
        if self._mini is not None and not self.root.winfo_viewable():
            self._mini.renderer.draw(state, level)
        else:
            self.globe.draw(state, level)

        if state != self._last_state:
            self._last_state = state
            title, hint = STATE_LABELS.get(state, STATE_LABELS["idle"])
            from overlay import COLORS
            color = COLORS.get(state, ACCENT)
            self.status_title.configure(text=title, fg=color)
            if state == "boot":
                self.status_hint.configure(text=self.engine.boot_message)
            elif hint is not None:
                self.status_hint.configure(text=hint)
            elif state == "speaking":
                self.status_hint.configure(text="")
            chip_text = {"error": "●  OFFLINE — click to retry" if self._fatal else "●  PROBLEM",
                         "boot": "●  STARTING"}.get(state, "●  ONLINE")
            self.chip.configure(text=chip_text, fg=BAD if state == "error" else ACCENT if state == "boot" else GOOD,
                                cursor="hand2" if self._fatal else "arrow")
            self.talk_btn.set_enabled(self.engine.ready and state in ("idle", "paused"))

        hand = self.engine.hand_mouse_running()
        if hand != self._last_hand:
            self._last_hand = hand
            self.hand_btn.set_active(hand)

    def refresh_labels(self):
        import config
        speaking = getattr(config, "SPEAK_REPLIES", True)
        self.voice_btn.set_text(f"Voice replies: {'ON' if speaking else 'OFF'}")
        self.voice_btn.set_active(speaking)
        self.footer.configure(
            text=f"Chat: {config.GROQ_CHAT_MODEL}   ·   Speech: {config.GROQ_STT_MODEL}   ·   "
                 f"Hand-mouse hotkey: {config.HAND_MOUSE_HOTKEY.upper()}   ·   Log: jarvis.log")


NO_KEY_TEXT = "No Groq API key found — add one in Settings."


def main() -> None:
    setup_logging()
    prepare_windows()
    if "--selftest" in sys.argv:  # health check of the packaged program (see selftest.py); no window
        import selftest
        sys.exit(selftest.run())
    if already_running():
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, "Jarvis is already running.", "Jarvis", 0x40)
        except Exception:
            pass
        return

    import settings
    from dotenv import load_dotenv
    load_dotenv(settings.ENV_PATH)
    settings.load()

    root = tk.Tk()
    JarvisApp(root)
    root.mainloop()


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()  # needed once the app is bundled into an .exe
    main()
