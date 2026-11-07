"""A tiny thread-safe message bus between Jarvis's background threads and the window.

The voice engine, the text-to-speech helper and the keyboard hotkey all run on
their own threads, but Tkinter widgets may only be touched from the main thread.
So instead of poking the window directly, those threads call emit(), and the
window drains the queue ~30 times a second and updates itself.

It stays switched off (and costs nothing) in console mode — the window turns it
on with enable().
"""
import queue

_queue: "queue.Queue[dict]" = queue.Queue()
_enabled = False


def enable() -> None:
    global _enabled
    _enabled = True


def emit(kind: str, **data) -> None:
    """Queue an event like emit("user", text="open notepad"). Safe from any thread."""
    if _enabled:
        _queue.put({"type": kind, **data})


def drain(limit: int = 100) -> list:
    """Returns up to `limit` queued events (oldest first). Called by the window's timer."""
    items = []
    try:
        while len(items) < limit:
            items.append(_queue.get_nowait())
    except queue.Empty:
        pass
    return items
