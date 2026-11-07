# Jarvis — voice assistant for your PC

Say "Hey Jarvis," wait for it to respond, then say what you want. It listens
locally (no cloud service hears you until you've said the wake word), sends
your command's audio to Groq to get transcribed and turned into a reply, and
Groq either answers you directly or calls one of the PC-control tools in
`actions.py`.

## Quick start

**For your customer:** build the installer once with `build_installer.bat` (see
[BUILD_INSTALLER.md](BUILD_INSTALLER.md)) and give them the single file `release\Jarvis-Setup.exe`.
During setup they type their own Groq API key and Jarvis runs on it.

**For you, running from source:** follow the manual setup below (or run `build_installer.bat`
once, which also creates the `venv`), then `python app.py`.

## How it works

```
mic (always listening, local, free)
  → openWakeWord detects "hey jarvis"
  → records your command until you stop talking
  → Groq's Whisper endpoint transcribes that audio to text
  → the text goes to a Groq chat model, which answers or picks a tool
  → if it picks a tool, main.py runs the matching function from actions.py
    and sends the result back to Groq for a final spoken answer
  → the reply is spoken back to you
```

Nothing is sent to Groq until the wake word fires, so it's not continuously
streaming audio anywhere.

## Setup

**1. Install Python 3.10 or newer** from [python.org](https://python.org) if
you don't have it. On the installer's first screen, check **"Add python.exe
to PATH."**

**2. Open this folder in a terminal** (PowerShell or Command Prompt) and
create a virtual environment:

```powershell
py -m venv venv
venv\Scripts\activate
```

**3. Install the dependencies:**

```powershell
pip install -r requirements.txt
```

**4. Get a Groq API key.**

1. Go to [console.groq.com](https://console.groq.com) and sign up or log in
   (email, Google, or GitHub — no card needed for the free tier).
2. Open [console.groq.com/keys](https://console.groq.com/keys).
3. Click **Create API Key**, give it a name, and copy the value it shows you
   (starts with `gsk_`) — it's only shown once.

**5. Add your key.** Copy `.env.example` to a new file named `.env` in the
same folder, then open `.env` and paste your key in:

```
GROQ_API_KEY=gsk_your-actual-key-here
```

This `.env` file stays on your machine — it's never sent anywhere except to
Groq when the app calls the API, and `.gitignore` already excludes it if you
put this folder under git later.

**6. Run it:**

```powershell
python main.py
```

You should hear "Jarvis online." Say **"Hey Jarvis"**, wait for "Yes?", then
say your command — e.g. *"open notepad"*, *"what's 15% of 340"*, *"set
volume to 30"*, *"take a screenshot"*.

## The desktop app (recommended)

Instead of typing `python main.py` in a terminal, you can launch Jarvis like any
other app — one click, no console window.

**One-time setup:** double-click `create_shortcut.bat`. It puts a **Jarvis**
icon on your Desktop and in the Start menu (right-click it → *Pin to taskbar*
if you like). After that, just double-click **Jarvis**.

What you get in the window:

- **The globe** — blue when standing by, green while it hears you, purple while
  thinking, orange while speaking, grey when the mic is off. Click it to talk.
- **Talk** button — speak a command without saying "Hey Jarvis" first.
- **Wake word: ON/OFF** — switch the always-listening microphone off (Talk and
  typing still work).
- **Conversation** — everything you said, everything Jarvis answered, and each
  PC action it ran. Type a command in the box at the bottom and press Enter.
- **Quick controls** — volume, brightness, mute, screenshot, lock, hand mouse.
- **Settings** — paste your Groq API key (saved to `.env`), pick the chat and
  speech models, tune wake-word sensitivity and the "done talking" delay, change
  the hand-mouse hotkey, turn spoken replies on/off. Saved to `settings.json`.
- **Mini** — shrinks Jarvis to the small floating globe in the corner so it can
  keep listening out of the way. Drag it to move it, double-click to bring the
  window back, right-click for a menu.
- Closing the window quits Jarvis. Only one copy can run at a time.

If it won't start, double-click `run_debug.bat` instead: same app, but with a
console that shows the error. The app also writes `jarvis.log` next to itself.

`main.py` still works as the old console version.

## What it can do out of the box

| Say something like... | Tool |
|---|---|
| "open chrome" / "open notepad" | `open_app` |
| "close spotify" | `close_app` |
| "take a screenshot" | `take_screenshot` |
| "set the volume to 40" | `set_volume` |
| "mute" / "unmute" | `mute` |
| "set brightness to 60" | `set_brightness` |
| "start hand mouse" / "stop hand mouse" (or press `ctrl+alt+h`) | `start_hand_mouse` / `stop_hand_mouse` |
| "lock my pc" | `lock_pc` |
| "shut down" / "restart" | `shutdown_pc` / `restart_pc` (30s delay, cancellable) |
| "cancel shutdown" | `cancel_shutdown` |
| "find my resume" | `search_files` |
| "open github.com" / "search for X" | `open_website` |

Anything that isn't one of these, Groq just answers conversationally (general
questions, quick math, writing help, etc.) — no PC action needed.

**Hand mouse** tracks your hand with your webcam and drives the real cursor:
point your index finger to move it, pinch your thumb to your index finger to
drag (a quick touch-and-release clicks, holding it while moving your hand
drags), or pinch your thumb to your middle finger for a plain click. The
first time you start it, it silently downloads a small (~8MB) tracking
model from Google and caches it next to `hand_mouse.py` — after that it
starts instantly. `ctrl+alt+h` (configurable
as `HAND_MOUSE_HOTKEY` in `config.py`) toggles it on/off immediately, without
needing the wake word.

**Voice overlay:** a small always-on-top rotating wireframe globe sits in the
bottom-right corner of your screen (`overlay.py`) and changes color/pulse
with what Jarvis is doing — blue and gently breathing while idle, green and
its glowing core reacting live to your actual mic volume while it's
listening to your command, purple while it waits on Groq, and orange while
your reply is being spoken. The globe itself keeps spinning the whole time;
only the color and the core's pulse change. No setup needed and no extra
dependency — it uses `tkinter`, which ships with a normal python.org install.

## Adding more capabilities

This takes two edits, because Groq (unlike the old Gemini setup) needs an
explicit schema for every tool rather than reading one off a docstring:

1. Open `actions.py` and add a new function following the same pattern: a
   docstring, type-hinted arguments, and a short string return value.
2. Open `tools_schema.py` and add a matching JSON schema to `TOOLS_SCHEMA`,
   plus one line in `TOOL_FUNCTIONS` mapping its name to the function you just
   wrote. The existing entries are good templates to copy.

## Tuning

Most of what's adjustable lives in `config.py`:
- `GROQ_CHAT_MODEL` — the model that answers you and picks tools. Check
  [console.groq.com/docs/models](https://console.groq.com/docs/models) for
  the current lineup if you want to try a different one.
- `GROQ_STT_MODEL` — `whisper-large-v3-turbo` (fast) or `whisper-large-v3`
  (more accurate, a bit slower) for transcribing your commands.
- `HAND_MOUSE_HOTKEY` — the keyboard shortcut that toggles hand mouse on/off.
  Defaults to `ctrl+alt+h`; change it if that clashes with something else you
  use (syntax follows the `keyboard` library, e.g. `"f9"` or `"ctrl+shift+m"`).
- `HAND_MOUSE_DEBUG_WINDOW` in `config.py` — shows a live preview window with
  your tracked fingertips and current mode while hand mouse runs. Handy while
  you're dialing gestures in; set to `False` once it feels right.
- Overlay look-and-feel lives at the top of `overlay.py`: `_SIZE`/`_MARGIN`
  control the window's size and distance from the corner, `_SPHERE_RADIUS`
  the globe's size, `_NUM_POINTS`/`_RING_SEGMENTS` its density (lower these
  if it feels laggy on your machine), `_ROTATION_SPEED`/`_TILT` how it spins
  and leans, `_COLORS` the per-state colors, and `_CORE_BASE_RADIUS`/
  `_CORE_MAX_RADIUS` how much the glowing core swells with the voice pulse.
  `_LEVEL_FOR_FULL_PULSE` near the top of `audio_io.py` controls how loud you
  need to talk for that pulse to hit full size.
- `WAKE_WORD_THRESHOLD` — lower it if "hey jarvis" isn't triggering, raise it
  if it triggers on its own too often.
- `SILENCE_THRESHOLD` / `SILENCE_SECONDS` — controls when it decides you've
  stopped talking. If it cuts you off mid-sentence, raise `SILENCE_THRESHOLD`
  or increase `SILENCE_SECONDS`.

## Troubleshooting

- **`pip install` fails on `PyAudioWPatch` or `pycaw`** — make sure you're
  using a 64-bit Python from python.org (not the Microsoft Store version),
  and that you're running the command *inside* the activated `venv`
  (prompt should show `(venv)`).
- **It never hears the wake word** — check Windows' default microphone
  (Settings → System → Sound) is the mic you're actually using, and try
  lowering `WAKE_WORD_THRESHOLD` in `config.py` to `0.4`.
- **`shutdown_pc` / `restart_pc` don't do anything** — some managed/work PCs
  block the `shutdown` command via policy; that's a Windows admin setting,
  not a bug in this script.
- **"No GROQ_API_KEY found"** — double check the file is literally named
  `.env` (not `.env.example` or `.env.txt`) and sits next to `main.py`.
- **"invalid_api_key" or 401 errors** — the key may have been copied with a
  trailing space, or revoked. Generate a fresh one at
  [console.groq.com/keys](https://console.groq.com/keys).
- **It mishears short or quiet commands** — that's the Whisper transcription
  step; try `whisper-large-v3` instead of the turbo model in `config.py`, or
  speak a touch closer to the mic.
- **"Set volume to X" / "mute" fails or does nothing** — first check whether
  it's a Windows/COM problem or a "the model didn't call the tool" problem by
  testing the function directly, bypassing voice entirely:
  ```powershell
  python -c "import comtypes; comtypes.CoInitialize(); import actions; print(actions.set_volume(40))"
  ```
  If that prints `Volume set to 40 percent.` and your actual system volume
  changes, the underlying code is fine — the issue is the chat model
  sometimes not calling the tool, which is worth mentioning if you're
  hitting this a lot. If it prints an error instead, share that exact text —
  it tells you (and me) precisely what's failing.
- **Hand mouse's cursor moves wrong, jumps around, or won't reach the screen
  edges** — `config.HAND_MOUSE_DEBUG_WINDOW` is off by default in this edition (tick it in Settings), so start hand
  mouse and watch the small preview window it opens: a green dot on your
  index fingertip, blue on middle, red on thumb, plus text showing MOVE,
  DRAG, "idle", or a "click!" flash. That tells you exactly what's being
  tracked. A few things to try, all near the top of `hand_mouse.py`:
  - **Cursor feels mirrored backwards** (moves left when your hand goes
    right) — set `_MIRROR = False`.
  - **Can't reach the screen edges without your hand leaving the camera
    view** — raise `_ACTIVE_MARGIN` further (e.g. `0.22` → `0.28`) so even
    less hand movement covers the whole screen. Going too high starts to
    make fine positioning twitchier, so nudge it up gradually.
  - **Cursor is jittery** — lower `_FILTER_MIN_CUTOFF` further (e.g. `0.7` →
    `0.4`) for a steadier cursor while your hand is nearly still.
  - **Cursor feels laggy or sluggish when you move your hand quickly** —
    raise `_FILTER_BETA` (e.g. `0.4` → `0.7`) so fast movement is tracked
    with less delay (at the cost of a little more jitter during that fast
    movement specifically).
  - **Motion still looks stepped/choppy rather than fluid** — this is
    usually detection rate, not filtering: lower `_CAPTURE_WIDTH`/
    `_CAPTURE_HEIGHT` further (e.g. `640x480` → `480x360`) so mediapipe has
    less image to process per frame and can detect more often, and/or raise
    `_CURSOR_CATCHUP` (e.g. `0.35` → `0.5`) so the interpolation thread
    closes the gap to each new detection faster.
  - **Cursor trails noticeably behind fast hand movement** — lower
    `_CURSOR_CATCHUP` won't help this (it only affects how fast it reacts,
    not overall lag); that's more a sign detection itself isn't keeping up —
    try the capture-size reduction above.
- **Drag or click doesn't register, or fires when you don't mean it to** —
  with the debug window open, pinch thumb-to-index and watch for "DRAG"
  while held; pinch thumb-to-middle and watch for "click!". If pinches never
  register even on a clear pinch, raise `_PINCH_DISTANCE_RATIO` (e.g. `0.4`
  → `0.55`) so a looser pinch still counts. If they fire too easily on a
  relaxed hand, lower it (e.g. `0.4` → `0.3`). If a click accidentally drags
  a short distance, or a drag gets read as a click, that's usually your
  middle finger drifting close to the thumb during an index pinch (or vice
  versa) — spread your fingers a bit more before pinching.
- **Left mouse button seems stuck down after using hand mouse** — shouldn't
  happen (there's an automatic release if your hand leaves the frame or you
  stop hand mouse mid-drag), but if it ever does, just pinch thumb-to-index
  once more and release — that always sends a fresh mouseUp.
- **"Set brightness to X" does nothing on a desktop monitor** — brightness
  control needs DDC/CI support, which not every monitor/cable combo has
  enabled. Check your monitor's on-screen menu for a "DDC/CI" setting, and
  make sure it's connected over HDMI or DisplayPort rather than through a
  dock or KVM switch that might block it. Laptop built-in screens should work
  out of the box. If it errors instead of just doing nothing (something
  mentioning `wmi` or a COM/DLL failure), pywin32 sometimes needs its one-time
  registration step: run `python Scripts\pywin32_postinstall.py -install`
  from an elevated (Run as administrator) terminal inside your venv.
- **"Take a screenshot" does nothing / errors** — make sure `pillow` actually
  installed (`pip show pillow` inside the venv); it's what `pyautogui` uses
  to capture and save the image. If it's missing, `pip install pillow` and
  try again.
- **Hand mouse says it can't open the webcam** — close any other app that
  might be holding it (Zoom, Teams, the Windows Camera app), then try again.
  If you have more than one camera, `hand_mouse.py` uses camera index `0`;
  change that in `_HandMouse.start()` if it's picking the wrong one.
- **`pip install -r requirements.txt` installed both `opencv-python` and
  `opencv-contrib-python`** — `mediapipe` pulls in `opencv-contrib-python` on
  its own, and having both installed together can quietly conflict (they ship
  the same `cv2` files, so one installer can partially overwrite the other,
  which usually only shows up later as an import or DLL error, not at install
  time). Fix it once with `pip uninstall opencv-python -y` and keep
  `opencv-contrib-python` — it's a superset, so nothing in `hand_mouse.py`
  loses functionality. The `requirements.txt` above no longer lists
  `opencv-python` for this reason.
- **`pip install mediapipe` fails to find a wheel for your Python version** —
  mediapipe hit 1.0 and now installs cleanly on current Python releases
  (confirmed working on 3.14); this mainly bites people on a very new Python
  release from the last few weeks, before mediapipe has published a wheel for
  it yet. If it happens, either wait a few days for mediapipe to catch up, or
  install Python 3.12/3.11 alongside your current one and create the venv
  with that instead (`py -3.12 -m venv venv`).
- **The overlay circle shows as a solid black square instead of just a
  floating circle** — your Windows setup isn't honoring the
  transparent-color trick `overlay.py` uses (rare, but can happen with some
  display/compositing configurations or over Remote Desktop). It'll still
  work and animate correctly, just as a square instead of a circle; there's
  no simple universal fix, so it's easiest to just live with it or pick a
  different `_BG` color near the top of `overlay.py` in case a specific color
  behaves better on your machine.
- **No overlay window appears at all** — check the console for a Tcl-related
  error right after "Jarvis online." A normal python.org install includes
  `tkinter` by default, but if yours was a custom/minimal install without it,
  reinstall Python from [python.org](https://python.org) and make sure "tcl/tk
  and IDLE" stays checked on the installer's customize screen. Jarvis still
  runs fine without it — you just won't get the visual.
- **Overlay animation feels choppy or laggy** — lower `_NUM_POINTS` and/or
  `_RING_SEGMENTS` near the top of `overlay.py` (e.g. `100` → `60`); fewer
  points to redraw each frame is the main cost.
- **Overlay sits behind other always-on-top windows, or in an inconvenient
  spot** — edit `_MARGIN`/`_SIZE` near the top of `overlay.py` to reposition
  or resize it; there's no in-app way to drag it since it has no title bar.

## A couple of things worth knowing

- Groq's free tier is generous for personal use, with per-minute request and
  token limits rather than a hard monthly cap — check current numbers at
  [console.groq.com/docs/rate-limits](https://console.groq.com/docs/rate-limits)
  if you're curious, or want to raise them.
- Every command now makes two Groq calls under the hood (one to transcribe
  the audio, one for the chat/tool-calling reply) instead of Gemini's single
  multimodal call — Groq's hardware is fast enough that this is still
  effectively instant in practice.
- `shutdown_pc`/`restart_pc` give you a real 30-second window to say "cancel
  shutdown" before anything happens, specifically so a misheard command can't
  actually take your PC down.
- This never phones home anywhere except to Groq's API — everything else
  (wake word detection, mic recording, hand-mouse webcam tracking, the voice
  overlay, the actual PC actions) runs entirely on your machine. Your webcam
  feed for hand mouse never leaves your PC; the only network call it ever
  makes is the one-time model download.
