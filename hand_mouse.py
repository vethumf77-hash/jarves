"""Webcam hand-tracking mouse control.

Runs MediaPipe's HandLandmarker task on your webcam feed in a background
thread and drives the real mouse with three gestures:

- Index finger pointing up -> moves the cursor to follow the fingertip.
- Pinch thumb to index finger -> drag: mouse button goes down the moment you
  pinch, follows your hand while held, and releases the instant you let go.
  A quick touch-and-release behaves like a normal click, since that's just a
  very short drag.
- Pinch thumb to middle finger -> a dedicated left click (always just a
  click, regardless of how long you hold it).

Cursor smoothness works in two layers:
1. A "1€ filter" (_OneEuroFilter) smooths the raw, noisy fingertip position
   itself — heavy smoothing while it's nearly still, light smoothing while
   moving fast, so jitter doesn't turn into cursor shake.
2. That filtered position only updates as often as a hand can actually be
   detected in a frame (mediapipe on CPU is typically ~15-25fps, well below
   your screen's refresh rate), which on its own still looks stepped. A
   separate _cursor_mover loop runs independently at _CURSOR_TICK_HZ and
   continuously eases the real cursor toward the latest filtered position,
   filling in the gaps between detections so the motion reads as continuous
   instead of jumping once per detected frame.

Toggle the whole thing by voice ("start/stop hand mouse") or with the hotkey
set in config.HAND_MOUSE_HOTKEY. If config.HAND_MOUSE_DEBUG_WINDOW is True, a
small preview window shows your tracked fingertips and the current mode
(MOVE / DRAG / click!) live — very useful for confirming which gesture is
firing; turn it off once things feel right.

Note: this uses MediaPipe's newer Tasks API (HandLandmarker) rather than the
older `mp.solutions.hands` you'll see in a lot of tutorials online — that API
was removed in recent mediapipe releases, so this is the current way to do
hand tracking in Python.
"""
import logging
import math
import os
import threading
import time
import urllib.request

import cv2
import mediapipe as mp
import pyautogui

import config
import events
import paths

pyautogui.FAILSAFE = False  # a moving hand near the screen edge shouldn't abort mid-gesture

_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/1/hand_landmarker.task"
)
_MODEL_PATH = str(paths.DATA_DIR / "hand_landmarker.task")            # downloaded here if needed
_BUNDLED_MODEL_PATH = str(paths.RESOURCE_DIR / "hand_landmarker.task")  # shipped inside the installer

_MIRROR = True  # flip the camera feed so moving your hand right moves the cursor right.
                # If left/right feels backwards on your setup, flip this to False.

_CAPTURE_WIDTH, _CAPTURE_HEIGHT = 640, 480  # a laptop webcam often defaults to something
                                             # much higher (720p/1080p), which slows down
                                             # every step (color conversion + detection) and
                                             # lowers how often the fingertip position can
                                             # even update. Forcing a modest capture size —
                                             # plenty for hand tracking — is one of the
                                             # biggest single wins for overall smoothness.

_ACTIVE_MARGIN = 0.22  # trims this fraction off each edge of the frame before mapping to
                        # the screen, so a laptop webcam's narrower field of view still lets
                        # you reach every screen corner without stretching your arm to the
                        # camera's literal edge. Higher = less hand travel needed for the
                        # same screen distance (easier corners, slightly less fine control).
_FILTER_MIN_CUTOFF = 0.7  # lower = steadier/smoother cursor when your hand is nearly still,
                           # but a touch more lag catching up when you start moving again
_FILTER_BETA = 0.4         # higher = snappier / less laggy during fast hand movement, at
                            # the cost of a bit more jitter creeping back in while fast

_CURSOR_TICK_HZ = 120    # how often the separate interpolation loop nudges the real cursor —
                          # much faster than detection can run, which is what makes motion
                          # between detected frames look continuous instead of stepped
_CURSOR_CATCHUP = 0.35   # fraction of the remaining distance to the latest target the
                          # cursor closes on each of those ticks — higher = snappier/more
                          # responsive, lower = silkier but trails your hand a bit more

_PINCH_DISTANCE_RATIO = 0.4  # pinch distance counted as "touching", as a fraction of the
                              # hand's own size — scales with how close your hand is to the
                              # camera, unlike a fixed distance. Lower = must pinch tighter.
_CLICK_COOLDOWN = 0.5  # seconds between clicks, so one held thumb-middle pinch doesn't
                        # repeatedly fire while held

# MediaPipe's landmark indices for the points this file cares about.
_WRIST = 0
_THUMB_TIP = 4
_INDEX_TIP, _INDEX_PIP = 8, 6
_MIDDLE_TIP, _MIDDLE_MCP = 12, 9


class _OneEuroFilter:
    """Smooths a noisy scalar signal over time: heavy smoothing while the signal is nearly
    still (kills jitter), lighter smoothing while it's changing fast (keeps up, low lag).
    The standard "1€ filter" (Casiez et al.) — applied here to the raw normalized fingertip
    x/y, before that gets mapped to screen pixels."""

    def __init__(self, min_cutoff: float, beta: float):
        self.min_cutoff = min_cutoff
        self.beta = beta
        self._x_prev = None
        self._dx_prev = 0.0
        self._t_prev = None

    @staticmethod
    def _alpha(cutoff: float, dt: float) -> float:
        tau = 1.0 / (2 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def reset(self) -> None:
        self._x_prev = None
        self._dx_prev = 0.0
        self._t_prev = None

    def __call__(self, x: float, t: float) -> float:
        if self._t_prev is None:
            self._x_prev, self._t_prev = x, t
            return x

        dt = max(t - self._t_prev, 1e-6)
        dx = (x - self._x_prev) / dt
        d_alpha = self._alpha(1.0, dt)
        dx_hat = d_alpha * dx + (1 - d_alpha) * self._dx_prev

        cutoff = self.min_cutoff + self.beta * abs(dx_hat)
        alpha = self._alpha(cutoff, dt)
        x_hat = alpha * x + (1 - alpha) * self._x_prev

        self._x_prev, self._dx_prev, self._t_prev = x_hat, dx_hat, t
        return x_hat


def _ensure_model() -> str:
    """Returns the hand-tracking model's path: the copy bundled with the installer if there is
    one, otherwise downloads the ~8MB model into Jarvis's data folder the first time it's needed."""
    for candidate in (_BUNDLED_MODEL_PATH, _MODEL_PATH):
        if os.path.exists(candidate):
            return candidate
    urllib.request.urlretrieve(_MODEL_URL, _MODEL_PATH)
    return _MODEL_PATH


def _finger_up(landmarks, tip_idx: int, pip_idx: int) -> bool:
    """True if this fingertip sits meaningfully higher than its middle knuckle — a simple
    "is this finger extended" check that works well for a hand held upright facing the
    camera."""
    return landmarks[tip_idx].y < landmarks[pip_idx].y - 0.02


def _hand_scale(landmarks) -> float:
    """Wrist-to-middle-knuckle distance, as a stand-in for "how big the hand looks right
    now" — used to scale the pinch thresholds so they work the same whether your hand is
    close to the camera or further away."""
    wrist, middle_mcp = landmarks[_WRIST], landmarks[_MIDDLE_MCP]
    return max(((wrist.x - middle_mcp.x) ** 2 + (wrist.y - middle_mcp.y) ** 2) ** 0.5, 1e-6)


def _pinch_dist(a, b, scale: float) -> float:
    """Distance between two landmarks, scaled by hand size so the same threshold works
    regardless of how close the hand is to the camera."""
    return (((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5) / scale


def _map_to_screen(value: float, screen_size: float) -> float:
    """Maps a normalized 0-1 camera coordinate to the full 0-screen_size range, using only
    the central [_ACTIVE_MARGIN, 1-_ACTIVE_MARGIN] slice of the frame — so a comfortable
    hand movement covers the whole screen instead of only the middle of it."""
    span = 1 - 2 * _ACTIVE_MARGIN
    normalized = (value - _ACTIVE_MARGIN) / span
    normalized = max(0.0, min(1.0, normalized))
    return normalized * screen_size


class _HandMouse:
    def __init__(self):
        self._lock = threading.Lock()
        self._running = False
        self._stop_event = None   # one Event per run: an old run can never be "revived" by a new start()
        self._threads = []

        # Shared between the vision thread (writer) and the cursor-mover thread (reader):
        # the latest on-screen point the cursor should be heading toward, or None to hold
        # position. A plain lock is plenty since this is just two floats, read/written often.
        self._target_lock = threading.Lock()
        self._target = None

    def is_running(self) -> bool:
        # A plain read, on purpose: the window polls this ~30 times a second, and taking the lock
        # here froze the whole UI while start() was busy downloading the model / opening the camera.
        return self._running

    def start(self) -> str:
        with self._lock:
            if self._running:
                return "Hand mouse is already running."

            try:
                model_path = _ensure_model()
            except Exception as e:
                return f"Couldn't download the hand-tracking model: {e}"

            cam = cv2.VideoCapture(0, cv2.CAP_DSHOW)
            if not cam.isOpened():
                cam.release()
                return "Couldn't open the webcam — check nothing else (Zoom, Teams, camera app) has it locked."
            cam.set(cv2.CAP_PROP_FRAME_WIDTH, _CAPTURE_WIDTH)
            cam.set(cv2.CAP_PROP_FRAME_HEIGHT, _CAPTURE_HEIGHT)

            stop_event = threading.Event()
            self._stop_event = stop_event
            self._running = True
            self._target = None
            loop = threading.Thread(target=self._loop, args=(cam, model_path, stop_event), daemon=True)
            mover = threading.Thread(target=self._cursor_mover, args=(stop_event,), daemon=True)
            self._threads = [loop, mover]
            loop.start()
            mover.start()

        return (
            "Hand mouse started. Point your index finger to move the cursor. Pinch thumb "
            "to index finger to drag — a quick touch clicks, holding it drags. Pinch "
            "thumb to middle finger for a plain click."
        )

    def stop(self) -> str:
        with self._lock:
            if not self._running:
                return "Hand mouse isn't running."
            self._running = False
            stop_event, threads = self._stop_event, list(self._threads)
            stop_event.set()
        # Wait (briefly, outside the lock) until the camera has really been released, so
        # turning it off and straight back on can't leave two tracking loops fighting over it.
        for t in threads:
            if t is not threading.current_thread():
                t.join(timeout=2.0)
        return "Hand mouse stopped."

    def toggle(self) -> str:
        return self.stop() if self.is_running() else self.start()

    def _set_target(self, target) -> None:
        with self._target_lock:
            self._target = target

    def _cursor_mover(self, stop_event: threading.Event) -> None:
        """Runs independently of hand detection, at a fixed high rate, continuously easing
        the real cursor toward whatever the vision loop last reported — this is what turns
        infrequent, possibly uneven detections into motion that looks smooth and continuous."""
        cur_x, cur_y = pyautogui.position()
        tick_seconds = 1.0 / _CURSOR_TICK_HZ

        had_target = False
        while not stop_event.is_set():
            with self._target_lock:
                target = self._target

            if target is not None:
                if not had_target:
                    # The hand just (re)appeared: start easing from where the cursor REALLY is now,
                    # so using the touchpad/mouse in between doesn't make it snap back.
                    cur_x, cur_y = pyautogui.position()
                    had_target = True
                tx, ty = target
                cur_x += (tx - cur_x) * _CURSOR_CATCHUP
                cur_y += (ty - cur_y) * _CURSOR_CATCHUP
                pyautogui.moveTo(cur_x, cur_y, _pause=False)
            else:
                had_target = False

            stop_event.wait(tick_seconds)

    def _draw_debug(self, frame, landmarks, mode_text) -> None:
        h, w = frame.shape[:2]
        x0, y0 = int(_ACTIVE_MARGIN * w), int(_ACTIVE_MARGIN * h)
        x1, y1 = int((1 - _ACTIVE_MARGIN) * w), int((1 - _ACTIVE_MARGIN) * h)
        cv2.rectangle(frame, (x0, y0), (x1, y1), (0, 255, 255), 1)  # the "active" zone

        if landmarks:
            for idx, color in (
                (_INDEX_TIP, (0, 255, 0)),
                (_MIDDLE_TIP, (255, 0, 0)),
                (_THUMB_TIP, (0, 0, 255)),
            ):
                lm = landmarks[idx]
                cv2.circle(frame, (int(lm.x * w), int(lm.y * h)), 8, color, -1)

        cv2.putText(frame, mode_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        cv2.imshow("Hand Mouse preview", frame)
        cv2.waitKey(1)

    def _loop(self, cam: "cv2.VideoCapture", model_path: str, stop_event: threading.Event) -> None:
        """Thread entry point: runs the tracking loop and guarantees cleanup however it ends
        (including a crash while loading the model, which used to leave the button stuck "on")."""
        try:
            self._track(cam, model_path, stop_event)
        except Exception as e:
            logging.getLogger("jarvis").exception("Hand mouse crashed")
            events.emit("error", text=f"Hand mouse stopped unexpectedly: {e}")
        finally:
            cam.release()
            stop_event.set()  # also stops this run's cursor-mover thread
            with self._lock:
                if self._stop_event is stop_event:  # still the current run (not already replaced)
                    self._running = False

    def _track(self, cam: "cv2.VideoCapture", model_path: str, stop_event: threading.Event) -> None:
        with open(model_path, "rb") as f:  # from memory: model_asset_path can choke on non-ASCII user names
            model_bytes = f.read()
        landmarker = mp.tasks.vision.HandLandmarker.create_from_options(
            mp.tasks.vision.HandLandmarkerOptions(
                base_options=mp.tasks.BaseOptions(model_asset_buffer=model_bytes),
                running_mode=mp.tasks.vision.RunningMode.VIDEO,
                num_hands=1,
                min_hand_detection_confidence=0.6,
                min_tracking_confidence=0.5,
            )
        )

        screen_w, screen_h = pyautogui.size()
        x_filter = _OneEuroFilter(_FILTER_MIN_CUTOFF, _FILTER_BETA)
        y_filter = _OneEuroFilter(_FILTER_MIN_CUTOFF, _FILTER_BETA)
        show_debug = config.HAND_MOUSE_DEBUG_WINDOW

        is_dragging = False       # true between a mouseDown and its matching mouseUp
        was_index_pinching = False   # thumb-index pinch state last frame (drag trigger)
        was_middle_pinching = False  # thumb-middle pinch state last frame (click trigger)
        last_click = 0.0
        last_ts = 0               # MediaPipe needs strictly increasing timestamps

        try:
            while not stop_event.is_set():
                ok, frame = cam.read()
                if not ok:
                    time.sleep(0.05)
                    continue

                if _MIRROR:
                    frame = cv2.flip(frame, 1)
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                # monotonic (not wall-clock): a clock adjustment must not crash the tracker
                ts = max(int(time.monotonic() * 1000), last_ts + 1)
                last_ts = ts
                result = landmarker.detect_for_video(mp_image, ts)

                landmarks = result.hand_landmarks[0] if result.hand_landmarks else None
                mode_text = "no hand"

                if landmarks is None:
                    # Safety net: don't leave the mouse button stuck down if the hand
                    # disappears mid-drag, and don't let the filters or the cursor-mover's
                    # target carry stale state into whenever the hand next reappears.
                    if is_dragging:
                        pyautogui.mouseUp()
                        is_dragging = False
                    was_index_pinching = was_middle_pinching = False
                    x_filter.reset()
                    y_filter.reset()
                    self._set_target(None)
                else:
                    index_tip, middle_tip, thumb_tip = (
                        landmarks[_INDEX_TIP], landmarks[_MIDDLE_TIP], landmarks[_THUMB_TIP]
                    )
                    index_up = _finger_up(landmarks, _INDEX_TIP, _INDEX_PIP)
                    scale = _hand_scale(landmarks)
                    now = time.time()

                    index_pinching = _pinch_dist(thumb_tip, index_tip, scale) < _PINCH_DISTANCE_RATIO
                    middle_pinching = (
                        not index_pinching
                        and _pinch_dist(thumb_tip, middle_tip, scale) < _PINCH_DISTANCE_RATIO
                    )

                    # Filter the raw landmark, map it to a screen point, and hand that off
                    # to the cursor-mover thread — this loop never moves the mouse directly.
                    if index_up or is_dragging:
                        filtered_x = x_filter(index_tip.x, now)
                        filtered_y = y_filter(index_tip.y, now)
                        target_x = _map_to_screen(filtered_x, screen_w)
                        target_y = _map_to_screen(filtered_y, screen_h)
                        self._set_target((target_x, target_y))

                    # Drag: thumb-index touching directly drives the mouse button. A quick
                    # touch-and-release is just a very short drag, which acts like a click.
                    if index_pinching and not was_index_pinching:
                        pyautogui.mouseDown()
                        is_dragging = True
                    elif not index_pinching and was_index_pinching:
                        pyautogui.mouseUp()
                        is_dragging = False

                    # Click: thumb-middle touching, a dedicated click regardless of hold time.
                    if (
                        middle_pinching
                        and not was_middle_pinching
                        and (now - last_click) > _CLICK_COOLDOWN
                    ):
                        pyautogui.click()
                        last_click = now
                        mode_text = "click!"
                    elif is_dragging:
                        mode_text = "DRAG"
                    elif index_up:
                        mode_text = "MOVE"
                    else:
                        mode_text = "idle"

                    was_index_pinching, was_middle_pinching = index_pinching, middle_pinching

                if show_debug:
                    self._draw_debug(frame, landmarks, mode_text)
        finally:
            if is_dragging:
                pyautogui.mouseUp()
            landmarker.close()
            if show_debug:
                cv2.destroyAllWindows()


# One shared instance — actions.py's tool wrappers and main.py's hotkey both call into this.
controller = _HandMouse()
