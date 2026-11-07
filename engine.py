"""The Jarvis engine: wake word, recording, transcription, the chat/tool loop — as a class
that runs on its own background thread, so the window (app.py) never freezes.

Everything here is the same pipeline main.py runs in the console, with three differences:

- It's controlled from outside through a few thread-safe methods (talk_now(),
  send_text(), run_tool(), set_listening() ...). Those just drop a "job" in a queue;
  the engine thread picks them up between wake-word checks.
- It reports what's happening through events.emit() (what you said, what Jarvis
  said, which tools ran, errors), which the window turns into its conversation log.
- The engine thread is the ONLY thread that touches Windows COM (volume/mute via
  pycaw, speech via pyttsx3, the microphone). COM objects are fussy about threads,
  so every action — even a click on a volume slider — is routed through here.

Imports of the heavy libraries happen inside the thread (see _boot) so the window
can appear instantly and show "Starting up..." instead of freezing for a few seconds.
"""
import json
import logging
import os
import queue
import sys
import threading

import config
import events
from overlay import overlay

log = logging.getLogger("jarvis.engine")

# Same prompt as main.py — keep the two in sync if you edit one.
SYSTEM_PROMPT = """\
You are Jarvis, a voice assistant running on the user's own Windows PC. Every \
message you receive is a transcript of something the user just said out loud \
to you — either answer directly or call one of your tools to carry it out.

Rules:
- Keep replies short and conversational — one or two sentences. They're read \
aloud by text-to-speech, so never use markdown, bullet points, code blocks, \
or long lists.
- The user is speaking, not typing, so if a request is a little ambiguous, \
make the most reasonable choice yourself rather than asking a clarifying \
question.
- Only call a tool when the user is clearly asking for that PC action. For \
general conversation, questions, or anything that isn't one of your tools, \
just answer directly in your own words.
- shutdown_pc and restart_pc already build in a real cancellable delay, so \
call them as soon as the user asks — you don't need to get a separate \
confirmation first.
"""

# Hard cap on tool-call round trips per command, so a confused model can't loop forever.
MAX_TOOL_ROUNDS = 5
# How many past messages (besides the system prompt) are kept and re-sent each turn.
MAX_HISTORY = 30

NO_KEY_MESSAGE = "I need a Groq API key first. Open Settings and paste yours in."


class JarvisEngine:
    def __init__(self):
        self._jobs: "queue.Queue[tuple]" = queue.Queue()
        self._stop = threading.Event()
        self._thread = None
        self._listening = True
        self._need_key_announced = False

        self.ready = False          # True once everything is loaded and listening has begun
        self.boot_message = "Starting up..."

        self._client = None
        self._client_key = None
        self._messages = [{"role": "system", "content": SYSTEM_PROMPT}]

        # filled in by _boot(), on the engine thread
        self._np = None
        self._pyaudio = None
        self._pa = None
        self._groq_cls = None
        self._audio_io = None
        self._tools = None
        self._oww = None
        self._wake_key = None
        self._comtypes = None

    # ------------------------------------------------------------------
    # Public, thread-safe API (call these from the window)
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Starts the engine thread (no-op if it's already running)."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self.ready = False
        overlay.set_state("boot")
        self._thread = threading.Thread(target=self._run, name="jarvis-engine", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        self._jobs.put(("noop",))
        if self._thread is not None:
            self._thread.join(timeout)

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def listening(self) -> bool:
        return self._listening

    def set_listening(self, on: bool) -> None:
        """Turns the always-on wake-word microphone on or off. Talk-now still works when off."""
        self._listening = bool(on)
        self._jobs.put(("noop",))

    def talk_now(self) -> None:
        """Starts recording a command immediately, without needing the wake word."""
        self._jobs.put(("talk",))

    def send_text(self, text: str) -> None:
        """Treats typed text exactly like something you said out loud."""
        text = (text or "").strip()
        if text:
            self._jobs.put(("text", text))

    def run_tool(self, name: str, args: dict = None, speak: bool = False) -> None:
        """Runs one of the PC tools directly (no AI involved) — used by the quick-action buttons."""
        self._jobs.put(("tool", name, dict(args or {}), speak))

    def toggle_hand_mouse(self) -> None:
        self._jobs.put(("hand_mouse",))

    def say(self, text: str) -> None:
        self._jobs.put(("say", text))

    def refresh_levels(self) -> None:
        self._jobs.put(("levels",))

    def reset_conversation(self) -> None:
        self._jobs.put(("reset",))

    def set_api_key(self, key: str) -> None:
        """Called after the key is changed in Settings; the next request uses the new one."""
        os.environ["GROQ_API_KEY"] = (key or "").strip()
        self._need_key_announced = False

    def hand_mouse_running(self) -> bool:
        module = sys.modules.get("hand_mouse")  # only exists once the engine has booted
        if module is None:
            return False
        try:
            return module.controller.is_running()
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Engine thread
    # ------------------------------------------------------------------

    def _run(self) -> None:
        try:
            self._boot()
        except Exception as e:
            log.exception("Engine failed to start")
            overlay.set_state("error")
            events.emit("fatal", text=f"{type(e).__name__}: {e}")
            return

        self.ready = True
        overlay.set_state("idle")
        events.emit("ready")
        if not self._api_key():
            self._announce_need_key()
        self._query_levels()

        mic_error_shown = False
        while not self._stop.is_set():
            try:
                kind, payload = self._wait_for_trigger()
            except Exception as e:
                # e.g. no microphone / it was unplugged. Say so ONCE (not every few seconds), keep
                # retrying in the background, and meanwhile keep serving typed commands and buttons,
                # which used to sit unprocessed in the queue for as long as the mic was broken.
                log.exception("Listening failed")
                if not mic_error_shown:
                    mic_error_shown = True
                    events.emit(
                        "error",
                        text=f"Microphone problem: {e}. Jarvis can't hear the wake word until a microphone "
                             "is available (check Windows Sound settings). Typed commands still work.",
                    )
                overlay.set_state("error")
                try:
                    job = self._jobs.get(timeout=3.0)
                except queue.Empty:
                    job = None
                overlay.set_state("idle")
                if job is not None:
                    self._handle_job(job)
                continue
            mic_error_shown = False

            if kind == "stop":
                break
            if kind == "wake":
                self._handle_voice(announce=True)
            elif kind == "job":
                self._handle_job(payload)

        self._shutdown()

    def _boot(self) -> None:
        def step(text):
            self.boot_message = text
            events.emit("boot", text=text)

        step("Preparing audio system...")
        # Claim this thread for COM's single-threaded apartment before PyAudioWPatch's WASAPI
        # backend gets a chance to initialize COM itself in multi-threaded mode. pycaw (used for
        # volume/mute) needs STA, and once a thread's COM mode is set it can't be changed
        # afterwards — so this has to run before the PyAudio() call further down.
        import comtypes
        comtypes.CoInitialize()
        self._comtypes = comtypes

        step("Loading PC controls and hand tracking...")
        import numpy as np
        import pyaudiowpatch as pyaudio
        from groq import Groq
        import audio_io
        import tools_schema
        self._np, self._pyaudio, self._groq_cls = np, pyaudio, Groq
        self._audio_io, self._tools = audio_io, tools_schema

        step("Loading wake-word model...")
        import openwakeword
        from openwakeword.model import Model
        if not getattr(sys, "frozen", False):  # the installed program ships with the models already
            try:
                openwakeword.utils.download_models()
            except Exception as e:  # offline? fine as long as the model is already on disk
                log.warning("Wake-word model download check failed: %s", e)
        model_path = openwakeword.MODELS[config.WAKE_WORD]["model_path"]
        self._oww = Model(wakeword_models=[model_path])
        # The loaded model's key includes a version suffix (e.g. "hey_jarvis_v0.1"),
        # so read it back from the model itself instead of hardcoding it.
        self._wake_key = list(self._oww.models.keys())[0]

        step("Opening the microphone...")
        self._pa = pyaudio.PyAudio()

    def _shutdown(self) -> None:
        try:
            module = sys.modules.get("hand_mouse")
            if module is not None and module.controller.is_running():
                module.controller.stop()
        except Exception:
            pass
        try:
            if self._pa is not None:
                self._pa.terminate()
        except Exception:
            pass
        try:
            if self._comtypes is not None:
                self._comtypes.CoUninitialize()
        except Exception:
            pass
        self.ready = False

    # ------------------------------------------------------------------
    # Waiting: wake word, or a job from the window
    # ------------------------------------------------------------------

    def _wait_for_trigger(self):
        """Blocks until something needs doing. Returns ("wake", None), ("job", job),
        ("stop", None), or (None, None) meaning "nothing yet — just loop again"."""
        if self._stop.is_set():
            return "stop", None

        if not self._listening:
            # Microphone off: don't hold the mic open, just wait for a job.
            overlay.set_state("paused")
            try:
                return "job", self._jobs.get(timeout=0.25)
            except queue.Empty:
                return None, None

        overlay.set_state("idle")
        pyaudio, np = self._pyaudio, self._np
        stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=16000,
            input=True,
            frames_per_buffer=config.CHUNK_SIZE,
        )
        try:
            while True:
                if self._stop.is_set():
                    return "stop", None
                if not self._listening:
                    return None, None
                try:
                    return "job", self._jobs.get_nowait()
                except queue.Empty:
                    pass

                data = stream.read(config.CHUNK_SIZE, exception_on_overflow=False)
                audio = np.frombuffer(data, dtype=np.int16)
                prediction = self._oww.predict(audio)
                if prediction[self._wake_key] > config.WAKE_WORD_THRESHOLD:
                    return "wake", None
        finally:
            stream.stop_stream()
            stream.close()

    def _reset_wake_model(self) -> None:
        """Clears the wake-word model's memory of recent audio, so the "hey jarvis" that just
        triggered it (or Jarvis's own spoken reply) can't immediately trigger it again."""
        try:
            self._oww.reset()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Handling a command
    # ------------------------------------------------------------------

    def _handle_voice(self, announce: bool) -> None:
        a = self._audio_io
        try:
            if announce:
                a.speak("Yes?", log=False)
            overlay.set_state("listening")
            pcm = a.record_command(
                self._pa,
                chunk=config.CHUNK_SIZE,
                max_seconds=config.MAX_COMMAND_SECONDS,
                silence_limit=config.SILENCE_SECONDS,
                silence_threshold=config.SILENCE_THRESHOLD,
            )
            overlay.set_state("thinking")

            # If nothing louder than "silence" was ever captured, don't bother Whisper — it
            # tends to invent text ("Thank you.") out of pure silence.
            samples = self._np.frombuffer(pcm, dtype=self._np.int16)
            if samples.size == 0 or int(self._np.abs(samples).max()) < config.SILENCE_THRESHOLD:
                a.speak("I didn't hear anything.")
                return

            client = self._get_client()
            if client is None:
                self._announce_need_key(speak=True)
                return

            transcript = self._transcribe(client, a.pcm_to_wav_bytes(pcm))
            if not transcript:
                a.speak("I didn't catch that.")
                return
            self._process_text(transcript)
        except Exception as e:
            self._report_failure(e)
        finally:
            overlay.set_state("idle")
            self._reset_wake_model()

    def _transcribe(self, client, wav_bytes: bytes) -> str:
        """Sends the recorded command to Groq's Whisper endpoint and returns the text."""
        result = client.audio.transcriptions.create(
            file=("command.wav", wav_bytes),
            model=config.GROQ_STT_MODEL,
        )
        return (result.text or "").strip()

    def _process_text(self, text: str) -> None:
        """text -> chat model (+ tools) -> spoken reply. Rolls the history back if it fails."""
        events.emit("user", text=text)
        mark = len(self._messages)
        self._messages.append({"role": "user", "content": text})
        try:
            client = self._get_client()
            if client is None:
                del self._messages[mark:]
                self._announce_need_key(speak=True)
                return
            reply = self._get_reply(client)
        except Exception:
            del self._messages[mark:]  # don't leave a half-finished tool exchange behind
            raise
        self._trim_history()
        self._audio_io.speak(reply)

    def _get_reply(self, client) -> str:
        """Runs the chat-completion + tool-call loop until Groq gives a final text answer."""
        extra = {}
        if config.GROQ_CHAT_MODEL.startswith("openai/gpt-oss"):
            # Without this, gpt-oss's internal chain-of-thought can leak into message.content —
            # and it would be read straight out loud. Hide it, and keep it brief so
            # tool-calling round trips stay fast.
            extra["reasoning_format"] = "hidden"
            extra["reasoning_effort"] = config.GROQ_REASONING_EFFORT

        for _ in range(MAX_TOOL_ROUNDS):
            response = client.chat.completions.create(
                model=config.GROQ_CHAT_MODEL,
                messages=self._messages,
                tools=self._tools.TOOLS_SCHEMA,
                tool_choice="auto",
                **extra,
            )
            message = response.choices[0].message
            entry = {"role": "assistant", "content": message.content or ""}
            if message.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.function.name, "arguments": call.function.arguments or "{}"},
                    }
                    for call in message.tool_calls
                ]
            self._messages.append(entry)

            if not message.tool_calls:
                return (message.content or "Done.").strip()

            self._messages.extend(self._run_tool_calls(message))

        return "Sorry, that took too many steps — let's try something simpler."

    def _run_tool_calls(self, message) -> list:
        """Executes every tool call Groq asked for and returns the results as tool messages."""
        tool_messages = []
        for call in message.tool_calls:
            name = call.function.name
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            result = self._call_tool(name, args)
            tool_messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "name": name,
                "content": str(result),
            })
        return tool_messages

    def _call_tool(self, name: str, args: dict) -> str:
        func = self._tools.TOOL_FUNCTIONS.get(name)
        if func is None:
            result = f"Unknown tool '{name}'."
        else:
            try:
                result = func(**args)
            except Exception as e:
                log.exception("Tool %s failed", name)
                result = f"Error running {name}: {e}"
        events.emit("tool", name=name, args=args, result=str(result))
        if name in ("set_volume", "mute"):
            self._query_levels()
        return str(result)

    def _trim_history(self) -> None:
        """Keeps the conversation from growing forever (and eating tokens every turn)."""
        system, rest = self._messages[0], self._messages[1:]
        if len(rest) <= MAX_HISTORY:
            return
        rest = rest[-MAX_HISTORY:]
        # Start on a user message so we never keep a tool result without its tool call.
        for i, m in enumerate(rest):
            if m.get("role") == "user":
                rest = rest[i:]
                break
        else:
            rest = []
        self._messages = [system] + rest

    # ------------------------------------------------------------------
    # Jobs from the window
    # ------------------------------------------------------------------

    def _handle_job(self, job: tuple) -> None:
        kind = job[0]
        try:
            if kind == "talk":
                self._handle_voice(announce=False)
            elif kind == "text":
                overlay.set_state("thinking")
                try:
                    self._process_text(job[1])
                finally:
                    overlay.set_state("idle")
            elif kind == "tool":
                _, name, args, speak = job
                result = self._call_tool(name, args)
                if speak:
                    self._audio_io.speak(result)
            elif kind == "hand_mouse":
                self._toggle_hand_mouse()
            elif kind == "say":
                self._audio_io.speak(job[1])
            elif kind == "levels":
                self._query_levels()
            elif kind == "reset":
                self._messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            # "noop" just wakes the loop up
        except Exception as e:
            self._report_failure(e)
            overlay.set_state("idle")

    def _toggle_hand_mouse(self) -> None:
        import hand_mouse
        message = hand_mouse.controller.toggle()
        running = hand_mouse.controller.is_running()
        events.emit("system", text=message)
        events.emit("hand_mouse", running=running)
        if running:
            self._audio_io.speak("Hand mouse on.", log=False)
        elif message.startswith("Hand mouse stopped"):
            self._audio_io.speak("Hand mouse off.", log=False)
        else:
            self._audio_io.speak(message, log=False)  # an error, e.g. webcam busy

    def _query_levels(self) -> None:
        """Reads the current system volume/mute so the window's slider matches reality."""
        volume = muted = None
        try:
            import actions
            iface = actions._volume_interface()
            volume = int(round(iface.GetMasterVolumeLevelScalar() * 100))
            muted = bool(iface.GetMute())
        except Exception as e:
            log.info("Couldn't read volume: %s", e)
        events.emit("levels", volume=volume, muted=muted)

    # ------------------------------------------------------------------
    # Groq client / errors
    # ------------------------------------------------------------------

    @staticmethod
    def _api_key() -> str:
        return os.environ.get("GROQ_API_KEY", "").strip()

    def _get_client(self):
        key = self._api_key()
        if not key:
            return None
        if self._client is None or key != self._client_key:
            self._client = self._groq_cls(api_key=key)
            self._client_key = key
        return self._client

    def _announce_need_key(self, speak: bool = False) -> None:
        events.emit("need_key")
        if speak:
            self._audio_io.speak(NO_KEY_MESSAGE)
        self._need_key_announced = True

    def _report_failure(self, error: Exception) -> None:
        log.exception("Command failed")
        text = str(error)
        events.emit("error", text=text)
        lowered = text.lower()
        if "401" in text or "invalid_api_key" in lowered or "invalid api key" in lowered:
            events.emit("need_key")
            spoken = "Groq rejected my API key. Check it in Settings."
        elif "429" in text or "rate limit" in lowered:
            spoken = "I've hit Groq's rate limit. Give me a moment and try again."
        elif "connection" in lowered or "timed out" in lowered or "network" in lowered:
            spoken = "I can't reach Groq. Check your internet connection."
        else:
            spoken = "Sorry, something went wrong with that one."
        try:
            self._audio_io.speak(spoken, log=False)
        except Exception:
            pass
