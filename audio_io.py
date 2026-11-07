"""Microphone recording and text-to-speech helpers."""
import io
import logging
import threading
import wave

import numpy as np
import pyaudiowpatch as pyaudio
import pyttsx3

import config
import events
from overlay import overlay

SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2  # bytes -> 16-bit audio

# Roughly the mic level (0-32767 scale, see config.SILENCE_THRESHOLD) that counts as
# "speaking at full volume" for the overlay's listening-mode pulse. Lower this if the
# circle barely grows even when you're talking normally; raise it if it maxes out too easily.
_LEVEL_FOR_FULL_PULSE = 4000

_tts_engine = None
_tts_failed_once = False
_tts_lock = threading.Lock()  # the hand-mouse hotkey can trigger speak() from its own thread


def get_tts_engine():
    """Lazily creates a single shared pyttsx3 engine (re-creating it each call is slow)."""
    global _tts_engine
    if _tts_engine is None:
        _tts_engine = pyttsx3.init()
        _tts_engine.setProperty("rate", 175)
    return _tts_engine


def speak(text: str, log: bool = True) -> None:
    """Speaks text out loud via the local Windows TTS voice, and echoes it to the console.

    Guarded by a lock: the main voice loop and the hand-mouse hotkey can both call this from
    different threads, and pyttsx3's engine isn't safe to drive from two threads at once.
    Puts the overlay into its "speaking" pulse for the duration, back to "idle" after.

    The window app also gets the text (shown in its conversation) via events — pass
    log=False for throwaway filler like "Yes?" that doesn't belong in the transcript.
    If config.SPEAK_REPLIES is off, the text still shows but nothing is read aloud.
    """
    global _tts_engine, _tts_failed_once
    try:
        print(f"Jarvis: {text}")
    except Exception:  # an odd character in a reply must never break the command
        pass
    if log:
        events.emit("jarvis", text=text)
    if not getattr(config, "SPEAK_REPLIES", True):
        return
    with _tts_lock:
        overlay.set_state("speaking")
        try:
            engine = get_tts_engine()
            engine.say(text)
            engine.runAndWait()
        except Exception as e:
            # No/broken Windows voice: the reply is already on screen, so this must not turn a
            # working command into "something went wrong". Drop the engine so the next call
            # builds a fresh one, and tell the user once.
            logging.getLogger("jarvis").warning("Text-to-speech failed: %s", e)
            _tts_engine = None
            if not _tts_failed_once:
                _tts_failed_once = True
                events.emit("error", text=f"I couldn't speak that out loud ({e}). Replies will still show here.")
        finally:
            overlay.set_state("idle")


def pcm_to_wav_bytes(pcm_data: bytes) -> bytes:
    """Wraps raw 16-bit mono PCM audio in a WAV container, in memory."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm_data)
    return buf.getvalue()


def record_command(
    pa: "pyaudio.PyAudio",
    chunk: int,
    max_seconds: float,
    silence_limit: float,
    silence_threshold: int,
) -> bytes:
    """Records mic audio until the user stops talking, or max_seconds is hit.

    Simple energy-based "stop talking" detection: once the mic level has risen
    above silence_threshold at least once, recording stops after silence_limit
    seconds of the level staying below it again. Feeds each chunk's loudness to
    the overlay so its "listening" pulse tracks your actual voice in real time.
    """
    stream = pa.open(
        format=pyaudio.paInt16,
        channels=CHANNELS,
        rate=SAMPLE_RATE,
        input=True,
        frames_per_buffer=chunk,
    )
    frames = []
    started_talking = False
    silent_chunks = 0
    chunk_seconds = chunk / SAMPLE_RATE
    max_chunks = int(max_seconds / chunk_seconds)
    silence_chunk_limit = max(1, int(silence_limit / chunk_seconds))

    try:
        for _ in range(max_chunks):
            data = stream.read(chunk, exception_on_overflow=False)
            frames.append(data)

            level = np.abs(np.frombuffer(data, dtype=np.int16)).mean()
            overlay.set_level(level / _LEVEL_FOR_FULL_PULSE)

            if level > silence_threshold:
                started_talking = True
                silent_chunks = 0
            elif started_talking:
                silent_chunks += 1
                if silent_chunks > silence_chunk_limit:
                    break
    finally:
        stream.stop_stream()
        stream.close()

    return b"".join(frames)
