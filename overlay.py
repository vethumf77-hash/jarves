"""The rotating holographic globe, plus the shared "what is Jarvis doing" state.

Two separate jobs live in this file:

1. `overlay` — a tiny thread-safe holder for Jarvis's current state ("idle",
   "listening", "thinking", "speaking") and the live mic level. The voice engine
   calls overlay.set_state() / overlay.set_level() from its own threads exactly as
   before; whatever is drawing the globe just asks overlay.snapshot() each frame.

2. `GlobeRenderer` — draws the wireframe globe (a scattered "city lights" point
   cloud plus great-circle rings, spun with plain trigonometry) onto any Tkinter
   Canvas. The window app (app.py) uses it twice: the big globe in the main window
   and the small floating "mini mode" globe. For the old console version
   (main.py), overlay.start_floating() still gives you the original always-on-top
   corner globe in its own little window.

States and their colors:
- "idle"      — blue, a slow gentle breathing pulse, waiting for the wake word.
- "listening" — green, the core swells with how loud your mic input is.
- "thinking"  — purple, a steady pulse (and a faster spin) while Groq works.
- "speaking"  — orange, a steady pulse while the reply is read out loud.
- "paused"    — grey, the microphone is switched off in the app.
- "boot"      — cyan, Jarvis is still starting up.
- "error"     — red, something failed to start.

No extra dependency needed — tkinter ships with a normal python.org install.
"""
import math
import threading
import time
import tkinter as tk

_BASE_SIZE = 150       # every pixel measurement below is for a 150px-wide canvas and is
                        # scaled up proportionally for bigger ones
_SPHERE_RADIUS = 56    # wireframe globe radius in pixels
_NUM_POINTS = 100      # "city light" points scattered over the globe's surface
_RING_SEGMENTS = 40    # smoothness of each great-circle ring
_ROTATION_SPEED = 0.5  # radians/second the globe spins around its vertical axis
_TILT = 0.45           # fixed forward tilt (radians) so it reads as a globe, not a flat disc
_CORE_BASE_RADIUS = 6  # glowing core size at rest
_CORE_MAX_RADIUS = 15  # glowing core size at full pulse
_DIM_FACTOR = 0.30     # brightness of the far side of the globe, as a fraction of full color
_FLOAT_MARGIN = 24     # distance from the screen corner for the legacy floating overlay
_FLOAT_BG = "#010101"  # near-black — used as the "see-through" color on Windows

COLORS = {
    "idle": "#3b82f6",       # blue
    "listening": "#22c55e",  # green
    "thinking": "#a855f7",   # purple
    "speaking": "#f97316",   # orange
    "paused": "#64748b",     # slate grey
    "boot": "#06b6d4",       # cyan
    "error": "#ef4444",      # red
}


def _fibonacci_sphere(n: int) -> list:
    """n evenly-spread unit vectors (x, y, z) over a sphere's surface — the "city lights"."""
    points = []
    golden_angle = math.pi * (3 - math.sqrt(5))
    for i in range(n):
        y = 1 - (i / (n - 1)) * 2 if n > 1 else 0.0
        radius_at_y = math.sqrt(max(0.0, 1 - y * y))
        theta = golden_angle * i
        points.append((math.cos(theta) * radius_at_y, y, math.sin(theta) * radius_at_y))
    return points


def _ring(longitude: float, n: int) -> list:
    """A great-circle "meridian" of n unit points, passing through both poles at the given
    longitude (radians). Combining a few of these at different longitudes is what gives the
    wireframe its criss-cross look."""
    points = []
    for i in range(n + 1):  # +1 to close the loop back to the start
        t = 2 * math.pi * i / n
        points.append((math.cos(t) * math.cos(longitude), math.sin(t), math.cos(t) * math.sin(longitude)))
    return points


def _equator(n: int) -> list:
    points = []
    for i in range(n + 1):
        t = 2 * math.pi * i / n
        points.append((math.cos(t), 0.0, math.sin(t)))
    return points


def lerp_color(hex_color: str, brightness: float) -> str:
    """Scales a "#rrggbb" color toward black; brightness 1.0 = unchanged, 0.0 = black."""
    hex_color = hex_color.lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    brightness = max(0.0, min(1.0, brightness))
    return f"#{int(r * brightness):02x}{int(g * brightness):02x}{int(b * brightness):02x}"


class GlobeRenderer:
    """Draws the globe onto a Tk Canvas. Create it once, then call draw() every frame
    from the thread that owns the canvas.

    size: the canvas's width/height in pixels (the canvas should be square).
    hud:  add the glowing halo and slowly turning arcs around the globe — nice on the
          big main-window version, too busy for the tiny floating one.
    """

    def __init__(self, canvas: tk.Canvas, size: int, hud: bool = False, num_points: int = _NUM_POINTS):
        self.canvas = canvas
        self.size = size
        self.hud = hud
        k = size / _BASE_SIZE if not hud else size / (_BASE_SIZE * 1.40)
        # with hud on, the globe is drawn smaller than the canvas, leaving room for the halo
        self.k = k
        self.cx = self.cy = size / 2
        self.radius = _SPHERE_RADIUS * k
        self.core_base = _CORE_BASE_RADIUS * k
        self.core_max = _CORE_MAX_RADIUS * k
        self.dot_base = 1.2 * k
        self.dot_gain = 1.6 * k

        self._last_time = time.time()
        self._rotation = 0.0
        self._level = 0.0
        self._hud_angle = 0.0

        c, cx, cy, idle = canvas, self.cx, self.cy, COLORS["idle"]

        # HUD extras go first so everything else draws on top of them
        self._glow = None
        self._arcs = []
        self._halo = None
        if hud:
            self._glow = c.create_oval(0, 0, 0, 0, fill=idle, outline="")
            for r_factor, width in ((1.30, 1), (1.52, 2), (1.72, 1)):
                r = self.radius * r_factor
                arc = c.create_arc(cx - r, cy - r, cx + r, cy + r, start=0, extent=90,
                                   style=tk.ARC, outline=idle, width=max(1, int(width * k)))
                self._arcs.append((arc, r_factor))
            r = self.radius * 1.12
            self._halo = c.create_oval(cx - r, cy - r, cx + r, cy + r, outline=idle, width=1)

        self._edge = c.create_oval(
            cx - self.radius, cy - self.radius, cx + self.radius, cy + self.radius,
            outline=idle, width=1,
        )
        self._rings = [
            (c.create_line(0, 0, 0, 0, fill=idle, width=1), _ring(lon, _RING_SEGMENTS))
            for lon in (0.0, math.pi / 4, math.pi / 2, 3 * math.pi / 4)
        ] + [(c.create_line(0, 0, 0, 0, fill=idle, width=1), _equator(_RING_SEGMENTS))]
        self._dots = [
            (c.create_oval(0, 0, 0, 0, fill=idle, outline=""), p)
            for p in _fibonacci_sphere(num_points)
        ]
        self._core = c.create_oval(0, 0, 0, 0, fill=idle, outline="")

    def _project(self, pt):
        px, py, pz = pt
        # fixed forward tilt
        py, pz = py * math.cos(_TILT) - pz * math.sin(_TILT), py * math.sin(_TILT) + pz * math.cos(_TILT)
        # continuous spin
        rot = self._rotation
        px, pz = px * math.cos(rot) + pz * math.sin(rot), -px * math.sin(rot) + pz * math.cos(rot)
        return self.cx + px * self.radius, self.cy - py * self.radius, pz  # pz doubles as depth, -1..1

    def draw(self, state: str, level: float = 0.0) -> None:
        now = time.time()
        dt = min(0.1, now - self._last_time)
        self._last_time = now

        color = COLORS.get(state, COLORS["idle"])
        spin = _ROTATION_SPEED * (2.4 if state in ("thinking", "boot") else 0.3 if state == "paused" else 1.0)
        self._rotation += spin * dt
        self._hud_angle += dt * (140 if state in ("thinking", "boot") else 40)

        # smooth the mic level a little so the core swells instead of flickering
        self._level += (max(0.0, min(1.0, level)) - self._level) * 0.4

        if state == "listening":
            pulse = self._level
        elif state in ("speaking", "thinking"):
            pulse = (math.sin(now * 6) + 1) / 2
        elif state == "boot":
            pulse = (math.sin(now * 3) + 1) / 2
        elif state == "paused":
            pulse = 0.0
        else:
            pulse = (math.sin(now * 1.5) + 1) / 4  # gentle idle breathing

        c = self.canvas
        for item, point in self._dots:
            sx, sy, depth = self._project(point)
            brightness = _DIM_FACTOR + (1 - _DIM_FACTOR) * ((depth + 1) / 2)
            size = self.dot_base + self.dot_gain * ((depth + 1) / 2)
            c.coords(item, sx - size, sy - size, sx + size, sy + size)
            c.itemconfig(item, fill=lerp_color(color, brightness))

        ring_color = lerp_color(color, 0.45)
        for item, ring_points in self._rings:
            flat = []
            for point in ring_points:
                sx, sy, _ = self._project(point)
                flat.extend((sx, sy))
            c.coords(item, *flat)
            c.itemconfig(item, fill=ring_color)

        core_radius = self.core_base + (self.core_max - self.core_base) * pulse
        c.coords(self._core, self.cx - core_radius, self.cy - core_radius,
                 self.cx + core_radius, self.cy + core_radius)
        c.itemconfig(self._core, fill=color)
        c.itemconfig(self._edge, outline=lerp_color(color, 0.6))

        if self.hud:
            glow_r = self.radius * (0.55 + 0.22 * pulse)
            c.coords(self._glow, self.cx - glow_r, self.cy - glow_r, self.cx + glow_r, self.cy + glow_r)
            c.itemconfig(self._glow, fill=lerp_color(color, 0.10 + 0.10 * pulse))
            c.itemconfig(self._halo, outline=lerp_color(color, 0.35))
            for i, (arc, _) in enumerate(self._arcs):
                direction = -1 if i % 2 else 1
                c.itemconfig(arc, start=(self._hud_angle * direction * (1 + 0.35 * i)) % 360,
                             extent=70 + 25 * i, outline=lerp_color(color, 0.75 - 0.15 * i))


class OverlayState:
    """The shared, thread-safe "what is Jarvis doing right now" holder. See module docstring."""

    def __init__(self):
        self._lock = threading.Lock()
        self._state = "idle"
        self._level = 0.0
        self._closed = False
        self._floating_started = False

    # --- Called by the voice engine / audio code, from any thread ---

    def set_state(self, state: str) -> None:
        """state is one of "idle", "listening", "thinking", "speaking" (or "paused"/"boot"/"error")."""
        with self._lock:
            self._state = state

    def set_level(self, level: float) -> None:
        """Roughly 0.0-1.0 mic loudness; only visible while state == "listening"."""
        with self._lock:
            self._level = max(0.0, min(1.0, level))

    def close(self) -> None:
        with self._lock:
            self._closed = True

    # --- Called by whatever is drawing the globe ---

    def snapshot(self):
        with self._lock:
            return self._state, self._level

    def is_closed(self) -> bool:
        with self._lock:
            return self._closed

    # --- Console mode only (main.py) ---

    def start_floating(self) -> None:
        """Opens the original always-on-top corner globe in its own background thread.
        Only main.py (console mode) uses this — the window app draws its own globes."""
        with self._lock:
            if self._floating_started:
                return
            self._floating_started = True
        started = threading.Event()
        threading.Thread(target=self._run_floating, args=(started,), daemon=True).start()
        started.wait(timeout=5)

    def _run_floating(self, started: threading.Event) -> None:
        size = _BASE_SIZE
        try:
            root = tk.Tk()
            root.overrideredirect(True)        # no title bar / borders
            root.attributes("-topmost", True)  # always on top
            root.configure(bg=_FLOAT_BG)
            try:
                root.attributes("-transparentcolor", _FLOAT_BG)  # Windows-only
            except tk.TclError:
                pass  # falls back to a plain square window where this isn't supported
            x = root.winfo_screenwidth() - size - _FLOAT_MARGIN
            y = root.winfo_screenheight() - size - _FLOAT_MARGIN
            root.geometry(f"{size}x{size}+{x}+{y}")
            canvas = tk.Canvas(root, width=size, height=size, bg=_FLOAT_BG, highlightthickness=0)
            canvas.pack()
            renderer = GlobeRenderer(canvas, size)
        except tk.TclError:
            started.set()  # set_state/set_level stay safe to call; they just won't show anything
            return

        def tick():
            if self.is_closed():
                root.destroy()
                return
            state, level = self.snapshot()
            renderer.draw(state, level)
            root.after(33, tick)  # ~30fps

        started.set()
        root.after(33, tick)
        root.mainloop()


# One shared instance — the engine, audio_io.py and the window all use it.
overlay = OverlayState()
