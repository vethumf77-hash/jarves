"""Jarvis — a wake-word voice assistant that controls your Windows PC via Groq.

This is the console version. For the windowed app, run app.py (or the Jarvis desktop
shortcut — see create_shortcut.bat) instead.

Run it, wait for "Jarvis online", then say "Hey Jarvis" followed by your
command once it replies. Ctrl+C to quit.
"""
import json
import os
import sys

import comtypes
import keyboard
import numpy as np
import openwakeword
import pyaudiowpatch as pyaudio
from dotenv import load_dotenv
from groq import Groq
from openwakeword.model import Model

import config
import hand_mouse
from audio_io import pcm_to_wav_bytes, record_command, speak
from overlay import overlay
from tools_schema import TOOLS_SCHEMA, TOOL_FUNCTIONS

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

# Hard cap on tool-call round trips per command, so a confused model can't
# loop forever instead of ever giving you a spoken answer.
MAX_TOOL_ROUNDS = 5


def wait_for_wake_word(oww_model: Model, wake_key: str, pa: "pyaudio.PyAudio") -> None:
    """Blocks until the wake word is heard, listening in small chunks the whole time."""
    stream = pa.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=16000,
        input=True,
        frames_per_buffer=config.CHUNK_SIZE,
    )
    try:
        while True:
            data = stream.read(config.CHUNK_SIZE, exception_on_overflow=False)
            audio = np.frombuffer(data, dtype=np.int16)
            prediction = oww_model.predict(audio)
            if prediction[wake_key] > config.WAKE_WORD_THRESHOLD:
                return
    finally:
        stream.stop_stream()
        stream.close()


def transcribe(client: Groq, wav_bytes: bytes) -> str:
    """Sends the recorded command to Groq's Whisper endpoint and returns the text."""
    result = client.audio.transcriptions.create(
        file=("command.wav", wav_bytes),
        model=config.GROQ_STT_MODEL,
    )
    return (result.text or "").strip()


def run_tool_calls(message) -> list:
    """Executes every tool call Groq asked for and returns the results as tool messages."""
    tool_messages = []
    for call in message.tool_calls:
        func_name = call.function.name
        try:
            args = json.loads(call.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {}

        func = TOOL_FUNCTIONS.get(func_name)
        if func is None:
            result = f"Unknown tool '{func_name}'."
        else:
            try:
                result = func(**args)
            except Exception as e:
                result = f"Error running {func_name}: {e}"

        tool_messages.append({
            "role": "tool",
            "tool_call_id": call.id,
            "name": func_name,
            "content": str(result),
        })
    return tool_messages


def get_reply(client: Groq, messages: list) -> str:
    """Runs the chat-completion + tool-call loop until Groq gives a final text answer."""
    extra = {}
    if config.GROQ_CHAT_MODEL.startswith("openai/gpt-oss"):
        # Without this, gpt-oss's internal chain-of-thought can leak into message.content —
        # and main.py would read it straight out loud. Hide it, and keep it brief so
        # tool-calling round trips stay fast.
        extra["reasoning_format"] = "hidden"
        extra["reasoning_effort"] = config.GROQ_REASONING_EFFORT

    for _ in range(MAX_TOOL_ROUNDS):
        response = client.chat.completions.create(
            model=config.GROQ_CHAT_MODEL,
            messages=messages,
            tools=TOOLS_SCHEMA,
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
        messages.append(entry)  # plain dict, like engine.py: Groq rejects extra SDK fields (e.g. "reasoning")

        if not message.tool_calls:
            return (message.content or "Done.").strip()

        messages.extend(run_tool_calls(message))

    return "Sorry, that took too many steps — let's try something simpler."


def main() -> None:
    if os.name != "nt":
        print("This assistant is built for Windows (it uses pycaw and PyAudioWPatch).")
        sys.exit(1)

    overlay.start_floating()  # console mode only — the window app (app.py) draws its own globe
    load_dotenv()
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        print("No GROQ_API_KEY found. Copy .env.example to .env and add your key there.")
        sys.exit(1)

    print("Loading wake word model...")
    openwakeword.utils.download_models(); model_path = openwakeword.MODELS[config.WAKE_WORD]["model_path"]
    oww_model = Model(wakeword_models=[model_path])
    # The loaded model's key includes a version suffix (e.g. "hey_jarvis_v0.1"),
    # so read it back from the model itself instead of hardcoding it.
    wake_key = list(oww_model.models.keys())[0]

    # Claim this thread for COM's single-threaded apartment before PyAudioWPatch's WASAPI
    # backend gets a chance to initialize COM itself in multi-threaded mode. pycaw (used for
    # volume/mute) needs STA, and once a thread's COM mode is set it can't be changed
    # afterwards — so this has to run before the PyAudio() call right below it.
    comtypes.CoInitialize()

    pa = pyaudio.PyAudio()
    client = Groq(api_key=api_key)

    # Groq's chat completions are stateless per call, so — unlike the old Gemini
    # chat session — we keep the running conversation in this list ourselves and
    # send the whole thing back on every turn.
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Lets you flip hand-mouse on/off instantly, without going through the wake word.
    keyboard.add_hotkey(config.HAND_MOUSE_HOTKEY, lambda: speak(hand_mouse.controller.toggle()))

    speak(
        "Jarvis online. Say hey jarvis, then your command. "
        f"Or press {config.HAND_MOUSE_HOTKEY} to toggle hand mouse."
    )

    while True:
        try:
            print("\nListening for 'hey jarvis'...")
            wait_for_wake_word(oww_model, wake_key, pa)
            speak("Yes?")

            overlay.set_state("listening")
            pcm = record_command(
                pa,
                chunk=config.CHUNK_SIZE,
                max_seconds=config.MAX_COMMAND_SECONDS,
                silence_limit=config.SILENCE_SECONDS,
                silence_threshold=config.SILENCE_THRESHOLD,
            )
            overlay.set_state("thinking")
            wav_bytes = pcm_to_wav_bytes(pcm)

            transcript = transcribe(client, wav_bytes)
            if not transcript:
                speak("I didn't catch that.")
                continue
            print(f"You: {transcript}")

            messages.append({"role": "user", "content": transcript})
            reply = get_reply(client, messages)
            speak(reply)

        except KeyboardInterrupt:
            speak("Goodbye.")
            break
        except Exception as e:
            print(f"Error: {e}")
            speak("Sorry, something went wrong with that one.")

    keyboard.unhook_all_hotkeys()
    pa.terminate()
    comtypes.CoUninitialize()
    overlay.close()


if __name__ == "__main__":
    main()
