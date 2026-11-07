"""Central configuration for the Jarvis voice assistant.

Tweak these values to change behavior without digging through the other files.
"""

# --- Groq ---
# "openai/gpt-oss-120b" is a large, fast, tool-calling-capable reasoning model — built
# specifically for agentic/tool-use tasks, so it's a good fit for Jarvis. Swap in another
# Groq-hosted chat model if you want; check https://console.groq.com/docs/models for the
# current lineup and which ones support tool use.
GROQ_CHAT_MODEL = "openai/gpt-oss-120b"

# gpt-oss models think through a hidden chain-of-thought before answering. main.py already
# tells Groq to keep that out of the reply text (so it never gets spoken out loud) whenever
# GROQ_CHAT_MODEL starts with "openai/gpt-oss" — this just controls how much thinking it
# does first: "low" keeps voice replies fast; "medium"/"high" trade speed for better
# judgment on trickier requests.
GROQ_REASONING_EFFORT = "low"

# Speech-to-text model used to transcribe your recorded command before it's sent
# to the chat model above. "whisper-large-v3-turbo" is the fastest option and
# plenty accurate for short commands; switch to "whisper-large-v3" if you want
# the more accurate (but slower) variant.
GROQ_STT_MODEL = "whisper-large-v3-turbo"

# --- Window app ---
# Whether Jarvis reads its replies out loud. In the window app you can flip this from the
# "Voice" button or the Settings window; replies always show in the conversation either way.
SPEAK_REPLIES = True

# --- Hand mouse hotkey ---
# Global keyboard shortcut that toggles webcam hand-tracking mouse control on/off
# instantly, without needing to say "hey jarvis" first. Uses the `keyboard`
# library's hotkey syntax, e.g. "ctrl+alt+h" or "f9" — pick something unlikely
# to clash with shortcuts other apps already use.
HAND_MOUSE_HOTKEY = "ctrl+alt+h"

# Shows a small live webcam window with your tracked fingertips and current mode
# (MOVE/DRAG/idle/click) drawn on top — turn this on while you're dialing gestures
# in, since it makes it obvious whether tracking, mode-switching, or clicking is the part
# misbehaving. Set to False once it feels right; the window is unnecessary for daily use.
HAND_MOUSE_DEBUG_WINDOW = False  # customer edition: off (turn on in Settings while tuning)

# --- Wake word ---
WAKE_WORD = "hey_jarvis"     # one of openWakeWord's bundled models — see main.py
WAKE_WORD_THRESHOLD = 0.5    # 0-1. Lower = triggers more easily (more false positives).

# --- Microphone / recording ---
CHUNK_SIZE = 1280            # 80ms of audio at 16kHz — openWakeWord's native frame size
MAX_COMMAND_SECONDS = 12     # hard cap so a stuck mic can't record forever
SILENCE_SECONDS = 1.1        # how much silence in a row means "they're done talking"
SILENCE_THRESHOLD = 300      # mic input level (0-32767) counted as silence.
                              # Cutting you off mid-sentence? Raise this.
                              # Still listening after you've stopped talking? Lower it.
