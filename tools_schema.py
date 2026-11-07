"""OpenAI-style JSON schemas for Groq function calling, plus the dispatch table
that maps each schema's name back to the real Python function in actions.py.

Unlike the old Gemini SDK, Groq's chat-completion API doesn't build tool
schemas automatically from docstrings/type hints — you have to hand it exact
JSON schemas, and you're the one who runs the matching Python function and
feeds the result back. That's what this file + the loop in main.py do.

To add a new capability: write the function in actions.py as before, add a
matching schema below, and add one line to TOOL_FUNCTIONS.
"""
import actions

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "open_app",
            "description": (
                'Opens a desktop application by name, e.g. "chrome", "notepad", '
                '"spotify", "word".'
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {
                        "type": "string",
                        "description": "The application name, roughly as the user said it.",
                    }
                },
                "required": ["app_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "close_app",
            "description": 'Closes a running application by name, e.g. "chrome", "spotify".',
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {
                        "type": "string",
                        "description": "The application/process name, roughly as the user said it.",
                    }
                },
                "required": ["app_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "take_screenshot",
            "description": "Takes a screenshot of the whole screen and saves it to Pictures\\Screenshots.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_volume",
            "description": "Sets the system master volume to a specific percentage.",
            "parameters": {
                "type": "object",
                "properties": {
                    "level_percent": {
                        "type": "integer",
                        "description": "Target volume from 0 (silent) to 100 (max).",
                    }
                },
                "required": ["level_percent"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mute",
            "description": "Mutes or unmutes system audio.",
            "parameters": {
                "type": "object",
                "properties": {
                    "should_mute": {
                        "type": "boolean",
                        "description": "True to mute, False to unmute. Defaults to True.",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_brightness",
            "description": (
                "Sets the display brightness to a specific percentage. Works reliably on "
                "laptop built-in screens; external monitors need DDC/CI support enabled."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "level_percent": {
                        "type": "integer",
                        "description": "Target brightness from 0 (dimmest) to 100 (brightest).",
                    }
                },
                "required": ["level_percent"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "start_hand_mouse",
            "description": (
                "Starts webcam hand-tracking mouse control: pointing the index finger "
                "moves the cursor; pinching thumb to index finger drags (a quick touch "
                "clicks, holding it while moving drags); pinching thumb to middle finger "
                "is a plain click. Call this when the user asks to start, turn on, or "
                "enable hand mouse / hand tracking."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stop_hand_mouse",
            "description": (
                "Stops webcam hand-tracking mouse control. Call this when the user asks to "
                "stop, turn off, or disable hand mouse / hand tracking."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lock_pc",
            "description": (
                "Locks the PC. Fully reversible with the user's normal password/PIN — "
                "safe to call immediately without asking for confirmation first."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "shutdown_pc",
            "description": (
                "Schedules a shutdown after a short delay so the user has time to cancel "
                "it out loud. Safe to call as soon as the user asks — no need to ask for "
                "confirmation first, since the delay itself is the confirmation window."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "delay_seconds": {
                        "type": "integer",
                        "description": "Seconds before shutdown. Defaults to 30; don't go below 10.",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "restart_pc",
            "description": (
                "Schedules a restart after a short delay so the user has time to cancel "
                "it out loud. Safe to call as soon as the user asks — no need to ask for "
                "confirmation first, since the delay itself is the confirmation window."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "delay_seconds": {
                        "type": "integer",
                        "description": "Seconds before restart. Defaults to 30; don't go below 10.",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_shutdown",
            "description": "Cancels a previously scheduled shutdown or restart.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": (
                "Searches for files whose name contains the given text, inside Desktop, "
                "Documents and Downloads by default."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Text to look for in file names.",
                    },
                    "search_root": {
                        "type": "string",
                        "description": "Optional specific folder to search instead of the default folders.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_website",
            "description": (
                "Opens a website in the default browser. Give it a URL, or a plain "
                "phrase to Google."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url_or_query": {
                        "type": "string",
                        "description": (
                            'A URL like "github.com", or a search phrase like '
                            '"weather in london".'
                        ),
                    }
                },
                "required": ["url_or_query"],
            },
        },
    },
]

# Maps each schema name above back to the actual Python function that runs it.
TOOL_FUNCTIONS = {
    "open_app": actions.open_app,
    "close_app": actions.close_app,
    "take_screenshot": actions.take_screenshot,
    "set_volume": actions.set_volume,
    "mute": actions.mute,
    "set_brightness": actions.set_brightness,
    "start_hand_mouse": actions.start_hand_mouse,
    "stop_hand_mouse": actions.stop_hand_mouse,
    "lock_pc": actions.lock_pc,
    "shutdown_pc": actions.shutdown_pc,
    "restart_pc": actions.restart_pc,
    "cancel_shutdown": actions.cancel_shutdown,
    "search_files": actions.search_files,
    "open_website": actions.open_website,
}
