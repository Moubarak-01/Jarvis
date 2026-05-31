import asyncio
import re
import threading
import json
import sys
import os
import traceback
from pathlib import Path

# --- FIX: Resolve Qt DPI Awareness conflict and suppress warnings ---
if sys.platform == "win32":
    # Tell Qt to use the existing DPI awareness context instead of trying to set a new one
    os.environ["QT_QPA_PLATFORM"] = "windows:dpiawareness=0"
    # Suppress the specific warning log if it still appears
    os.environ["QT_LOGGING_RULES"] = "qt.qpa.window=false"


import sounddevice as sd
from google import genai
from google.genai import types
from ui import JarvisUI
from memory.memory_manager import (
    load_memory, update_memory, format_memory_for_prompt,
)
from memory.config_manager import get_gemini_key

from actions.file_processor import file_processor
from actions.flight_finder     import flight_finder
from actions.open_app          import open_app
from actions.weather_report    import weather_action
from actions.send_message      import send_message
from actions.reminder          import reminder
from actions.computer_settings import computer_settings
from actions.screen_processor  import screen_process
from actions.youtube_video     import youtube_video
from actions.desktop           import desktop_control
from actions.browser_control   import browser_control
from actions.file_controller   import file_controller
from actions.code_helper       import code_helper
from actions.dev_agent         import dev_agent
from actions.web_search        import web_search as web_search_action
from actions.computer_control  import computer_control
from actions.game_updater      import game_updater
from actions.persona_control   import persona_control
from actions.gmail_handler     import gmail_processor
from actions.outlook_handler   import outlook_processor
from actions.github_handler    import github_processor
from actions.timer             import timer_action
from actions.clipboard_action  import read_clipboard_action
from actions.system_status     import system_status


class ReconnectRequested(Exception):
    """Custom exception to trigger a session reset."""
    pass

def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
PROMPT_PATH     = BASE_DIR / "core" / "prompt.txt"
LIVE_MODEL          = "gemini-2.5-flash-native-audio-preview-12-2025"
CHANNELS            = 1
SEND_SAMPLE_RATE    = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE          = 1024

def _get_api_key() -> str:
    key = get_gemini_key()
    if not key:
        raise ValueError("❌ Gemini API Key not found! Please add it to your .env file or the UI.")
    return key


def _load_system_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        return (
            "You are JARVIS, Tony Stark's AI assistant. "
            "Be concise, direct, and always use the provided tools to complete tasks. "
            "Never simulate or guess results — always call the appropriate tool."
        )

_CTRL_RE = re.compile(r"<ctrl\d+>", re.IGNORECASE)

def _clean_transcript(text: str) -> str:    
    text = _CTRL_RE.sub("", text)
    text = re.sub(r"[\x00-\x08\x0b-\x1f]", "", text)
    return text.strip()

TOOL_DECLARATIONS = [
    {
        "name": "open_app",
        "description": (
            "Opens any application on the computer. "
            "Use this whenever the user asks to open, launch, or start any app, "
            "website, or program. Always call this tool — never just say you opened it."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "app_name": {
                    "type": "STRING",
                    "description": "Exact name of the application (e.g. 'WhatsApp', 'Chrome', 'Spotify')"
                }
            },
            "required": ["app_name"]
        }
    },
    {
        "name": "web_search",
        "description": "Searches the web for any information.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query":  {"type": "STRING", "description": "Search query"},
                "mode":   {"type": "STRING", "description": "search (default) or compare"},
                "items":  {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Items to compare"},
                "aspect": {"type": "STRING", "description": "price | specs | reviews"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "weather_report",
        "description": "Gives the weather report to user",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "city": {"type": "STRING", "description": "City name"}
            },
            "required": ["city"]
        }
    },
    {
        "name": "send_message",
        "description": "Sends a text message via WhatsApp, Telegram, or other messaging platform.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "receiver":     {"type": "STRING", "description": "Recipient contact name"},
                "message_text": {"type": "STRING", "description": "The message to send"},
                "platform":     {"type": "STRING", "description": "Platform: WhatsApp, Telegram, etc."}
            },
            "required": ["receiver", "message_text", "platform"]
        }
    },
    {
        "name": "reminder",
        "description": "Sets a timed reminder using Task Scheduler.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "date":    {"type": "STRING", "description": "Date in YYYY-MM-DD format"},
                "time":    {"type": "STRING", "description": "Time in HH:MM format (24h)"},
                "message": {"type": "STRING", "description": "Reminder message text"}
            },
            "required": ["date", "time", "message"]
        }
    },
    {
        "name": "youtube_video",
        "description": (
            "Controls YouTube. Use for: playing videos, summarizing a video's content, "
            "getting video info, or showing trending videos."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "play | summarize | get_info | trending (default: play)"},
                "query":  {"type": "STRING", "description": "Search query for play action"},
                "save":   {"type": "BOOLEAN", "description": "Save summary to Notepad (summarize only)"},
                "region": {"type": "STRING", "description": "Country code for trending e.g. TR, US"},
                "url":    {"type": "STRING", "description": "Video URL for get_info action"},
            },
            "required": []
        }
    },
    {
        "name": "screen_process",
        "description": (
            "Captures and analyzes the screen or webcam image. "
            "MUST be called when user asks what is on screen, what you see, "
            "analyze my screen, look at camera, etc. "
            "You have NO visual ability without this tool. "
            "After calling this tool, stay SILENT — the vision module speaks directly."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "angle": {"type": "STRING", "description": "'screen' to capture display, 'camera' for webcam. Default: 'screen'"},
                "text":  {"type": "STRING", "description": "The question or instruction about the captured image"},
                "monitor": {"type": "STRING", "description": "active | 0 (all) | 1 | 2 | 3 (default: active)"},
                "preview": {"type": "STRING", "description": "on | off (controls the live camera preview window in the UI)"}
            },
            "required": []
        }
    },
    {
        "name": "computer_settings",
        "description": (
            "Controls the computer: volume, brightness, window management, keyboard shortcuts, "
            "typing text on screen, closing apps, fullscreen, dark mode, WiFi, restart, shutdown, "
            "scrolling, tab management, zoom, screenshots, lock screen, refresh/reload page. "
            "Use for ANY single computer control command. NEVER route to agent_task."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "The action to perform"},
                "description": {"type": "STRING", "description": "Natural language description of what to do"},
                "value":       {"type": "STRING", "description": "Optional value: volume level, text to type, etc."}
            },
            "required": []
        }
    },
    {
        "name": "browser_control",
        "description": (
            "Controls any web browser. Use for: opening websites, searching the web, "
            "clicking elements, filling forms, scrolling, screenshots, navigation, any web-based task. "
            "Always pass the 'browser' parameter when the user specifies a browser (e.g. 'open in Edge', "
            "'use Firefox', 'open Chrome'). Multiple browsers can run simultaneously."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "go_to | search | click | type | scroll | fill_form | smart_click | smart_type | get_text | get_url | press | new_tab | close_tab | screenshot | back | forward | reload | switch | list_browsers | close | close_all"},
                "browser":     {"type": "STRING", "description": "Target browser: chrome | edge | firefox | opera | operagx | brave | vivaldi | safari. Omit to use the currently active browser."},
                "url":         {"type": "STRING", "description": "URL for go_to / new_tab action"},
                "query":       {"type": "STRING", "description": "Search query for search action"},
                "engine":      {"type": "STRING", "description": "Search engine: google | bing | duckduckgo | yandex (default: google)"},
                "selector":    {"type": "STRING", "description": "CSS selector for click/type"},
                "text":        {"type": "STRING", "description": "Text to click or type"},
                "description": {"type": "STRING", "description": "Element description for smart_click/smart_type"},
                "direction":   {"type": "STRING", "description": "up | down for scroll"},
                "amount":      {"type": "INTEGER", "description": "Scroll amount in pixels (default: 500)"},
                "key":         {"type": "STRING", "description": "Key name for press action (e.g. Enter, Escape, F5)"},
                "path":        {"type": "STRING", "description": "Save path for screenshot"},
                "incognito":   {"type": "BOOLEAN", "description": "Open in private/incognito mode"},
                "clear_first": {"type": "BOOLEAN", "description": "Clear field before typing (default: true)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "file_controller",
        "description": "Manages files and folders: list, create, delete, move, copy, rename, read, write, find, disk usage.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "list | create_file | create_folder | delete | move | copy | rename | read | write | find | largest | disk_usage | organize_desktop | info"},
                "path":        {"type": "STRING", "description": "File/folder path or shortcut: desktop, downloads, documents, home"},
                "destination": {"type": "STRING", "description": "Destination path for move/copy"},
                "new_name":    {"type": "STRING", "description": "New name for rename"},
                "content":     {"type": "STRING", "description": "Content for create_file/write"},
                "name":        {"type": "STRING", "description": "File name to search for"},
                "extension":   {"type": "STRING", "description": "File extension to search (e.g. .pdf)"},
                "count":       {"type": "INTEGER", "description": "Number of results for largest"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "desktop_control",
        "description": "Controls the desktop: wallpaper, organize, clean, list, stats.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "wallpaper | wallpaper_url | organize | clean | list | stats | task"},
                "path":   {"type": "STRING", "description": "Image path for wallpaper"},
                "url":    {"type": "STRING", "description": "Image URL for wallpaper_url"},
                "mode":   {"type": "STRING", "description": "by_type or by_date for organize"},
                "task":   {"type": "STRING", "description": "Natural language desktop task"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "code_helper",
        "description": "Writes, edits, explains, runs, or builds code files.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "write | edit | explain | run | build | auto (default: auto)"},
                "description": {"type": "STRING", "description": "What the code should do or what change to make"},
                "language":    {"type": "STRING", "description": "Programming language (default: python)"},
                "output_path": {"type": "STRING", "description": "Where to save the file"},
                "file_path":   {"type": "STRING", "description": "Path to existing file for edit/explain/run/build"},
                "code":        {"type": "STRING", "description": "Raw code string for explain"},
                "args":        {"type": "STRING", "description": "CLI arguments for run/build"},
                "timeout":     {"type": "INTEGER", "description": "Execution timeout in seconds (default: 30)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "dev_agent",
        "description": "Builds complete multi-file projects from scratch: plans, writes files, installs deps, opens requested IDE, runs and fixes errors.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "description":  {"type": "STRING", "description": "What the project should do"},
                "language":     {"type": "STRING", "description": "Programming language (e.g. python, javascript, rust). Default: python"},
                "project_name": {"type": "STRING", "description": "Optional project folder name"},
                "timeout":      {"type": "INTEGER", "description": "Run timeout in seconds (default: 30)"},
                "ide":          {"type": "STRING", "description": "The IDE to open: 'vscode', 'antigravity', or 'none'. You MUST ask the user their preference before running this tool, or default to 'none' if they didn't specify."},
                "deadline_minutes": {"type": "NUMBER", "description": "Optional deadline for the task in minutes (e.g. 5, 10.5)"},
            },
            "required": ["description"]
        }
    },
    {
        "name": "persona_control",
        "description": "Changes J.A.R.V.I.S.'s voice persona (Charon, Aoede, Puck, or Kore).",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "voice_name": {"type": "STRING", "description": "The name of the voice: Charon | Aoede | Puck | Kore"}
            },
            "required": ["voice_name"]
        }
    },
    {
        "name": "agent_task",
        "description": (
            "Executes complex multi-step tasks requiring multiple different tools. "
            "Examples: 'research X and save to file', 'find and organize files'. "
            "DO NOT use for single commands. NEVER use for Steam/Epic — use game_updater."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "goal":     {"type": "STRING", "description": "Complete description of what to accomplish"},
                "priority": {"type": "STRING", "description": "low | normal | high (default: normal)"},
                "deadline_minutes": {"type": "NUMBER", "description": "Optional deadline for the task in minutes"}
            },
            "required": ["goal"]
        }
    },
    {
        "name": "computer_control",
        "description": "Direct computer control. Use 'screen_click' to click elements by name. DO NOT use 'smart_click' or 'smart_move' — they do not exist.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "type | smart_type | click | double_click | right_click | hotkey | press | scroll | move | move_to | circular_move | square_move | rectangular_move | copy | paste | screenshot | wait | clear_field | focus_window | screen_find | screen_click | screen_double_click | screen_right_click | random_data | user_data | window_control | list_windows | media_control | lock_screen | launch_app | read_screen_text. 'move' = RELATIVE (shifts cursor by x,y pixels from current position). 'move_to' = ABSOLUTE (moves cursor to exact screen coordinate x,y)."},
                "text":        {"type": "STRING", "description": "Text to type or paste"},
                "x":           {"type": "INTEGER", "description": "X coordinate (pixels). For 'move': relative offset (negative=left, positive=right). For 'move_to': absolute screen position."},
                "y":           {"type": "INTEGER", "description": "Y coordinate (pixels). For 'move': relative offset (negative=up, positive=down). For 'move_to': absolute screen position."},
                "keys":        {"type": "STRING", "description": "Key combination e.g. 'ctrl+c'"},
                "key":         {"type": "STRING", "description": "Single key e.g. 'enter'"},
                "direction":   {"type": "STRING", "description": "up | down | left | right"},
                "amount":      {"type": "INTEGER", "description": "Scroll amount (default: 3)"},
                "seconds":     {"type": "NUMBER",  "description": "Seconds to wait"},
                "title":       {"type": "STRING",  "description": "Window title for focus_window"},
                "description": {"type": "STRING",  "description": "Element description for screen_find/screen_click"},
                "type":        {"type": "STRING",  "description": "Data type for random_data"},
                "field":       {"type": "STRING",  "description": "Field for user_data: name|email|city"},
                "clear_first": {"type": "BOOLEAN", "description": "Clear field before typing (default: true)"},
                "path":        {"type": "STRING",  "description": "Save path for screenshot"},
                "radius":      {"type": "INTEGER", "description": "Radius in pixels for circular_move (e.g. 113 ≈ 3cm on a 96 DPI screen)"},
                "side":        {"type": "INTEGER", "description": "Side length in pixels for square_move"},
                "width":       {"type": "INTEGER", "description": "Width in pixels for rectangular_move"},
                "height":      {"type": "INTEGER", "description": "Height in pixels for rectangular_move"},
                "rotations":   {"type": "INTEGER", "description": "Number of full circles/squares for shape movements (default: 1)"},
                "duration":    {"type": "NUMBER",  "description": "Duration in seconds for shape animation. Increase this to make it go slower! (default: 4.0)"},
                "window_action":{"type": "STRING", "description": "minimize | maximize | restore | close"},
                "title":       {"type": "STRING",  "description": "Title of the window to control. Leave empty or use 'current' to target the active window."},
                "media_action": {"type": "STRING", "description": "volumeup | volumedown | mute | playpause | next | prev | space (use 'space' to pause/play videos in web browsers like YouTube/Netflix)"},
                "app_name":    {"type": "STRING",  "description": "Application name to launch via OS start"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "game_updater",
        "description": (
            "THE ONLY tool for ANY Steam or Epic Games request. "
            "Use for: installing, downloading, updating games, listing installed games, "
            "checking download status, scheduling updates. "
            "ALWAYS call directly for any Steam/Epic/game request. "
            "NEVER use agent_task, browser_control, or web_search for Steam/Epic."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":    {"type": "STRING",  "description": "update | install | list | download_status | schedule | cancel_schedule | schedule_status (default: update)"},
                "platform":  {"type": "STRING",  "description": "steam | epic | both (default: both)"},
                "game_name": {"type": "STRING",  "description": "Game name (partial match supported)"},
                "app_id":    {"type": "STRING",  "description": "Steam AppID for install (optional)"},
                "hour":      {"type": "INTEGER", "description": "Hour for scheduled update 0-23 (default: 3)"},
                "minute":    {"type": "INTEGER", "description": "Minute for scheduled update 0-59 (default: 0)"},
                "shutdown_when_done": {"type": "BOOLEAN", "description": "Shut down PC when download finishes"},
            },
            "required": []
        }
    },
    {
        "name": "flight_finder",
        "description": "Searches Google Flights and speaks the best options.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "origin":      {"type": "STRING",  "description": "Departure city or airport code"},
                "destination": {"type": "STRING",  "description": "Arrival city or airport code"},
                "date":        {"type": "STRING",  "description": "Departure date (any format)"},
                "return_date": {"type": "STRING",  "description": "Return date for round trips"},
                "passengers":  {"type": "INTEGER", "description": "Number of passengers (default: 1)"},
                "cabin":       {"type": "STRING",  "description": "economy | premium | business | first"},
                "save":        {"type": "BOOLEAN", "description": "Save results to Notepad"},
            },
            "required": ["origin", "destination", "date"]
        }
    },
    {
        "name": "shutdown_jarvis",
        "description": (
            "Shuts down the assistant completely. "
            "Call this when the user expresses intent to end the conversation, "
            "close the assistant, say goodbye, or stop Jarvis. "
            "The user can say this in ANY language."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
        }
    },
    {
        "name": "restart_jarvis",
        "description": (
            "Restarts the assistant completely. "
            "Call this when the user asks you to restart, reboot, or refresh yourself."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
        }
    },
    {
        "name": "timer",
        "description": "Starts or cancels a countdown timer.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":           {"type": "STRING", "description": "'start' to start a new timer, 'cancel' to stop an active timer.", "enum": ["start", "cancel"]},
                "duration_seconds": {"type": "NUMBER", "description": "Duration of the timer in seconds (required if action is 'start')"},
                "message":          {"type": "STRING", "description": "Message to speak when the timer finishes (if starting)"}
            },
            "required": ["action"]
        }
    },
    {
        "name": "toggle_virtual_control",
        "description": "Activate or deactivate virtual hand control (uses webcam to move mouse and click).",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "active": {"type": "BOOLEAN", "description": "True to activate, False to deactivate."}
            },
            "required": ["active"]
        }
    },
    {
        "name": "dock_camera_preview",
        "description": "Docks the floating camera preview back into its original place in the Jarvis UI.",
        "parameters": {
            "type": "OBJECT",
            "properties": {}
        }
    },
    {
        "name": "read_clipboard",
        "description": "Reads the current contents of the system clipboard out loud. Use when user asks to read what they copied or cut.",
        "parameters": {
            "type": "OBJECT",
            "properties": {}
        }
    },
    {
    "name": "file_processor",
    "description": (
        "Processes any file that the user has uploaded or dropped onto the interface. "
        "Use this when the user refers to an uploaded file and wants an action on it. "
        "Supports: images (describe/ocr/resize/compress/convert), "
        "PDFs (summarize/extract_text/to_word), "
        "Word docs & text files (summarize/fix/reformat/translate), "
        "CSV/Excel (analyze/stats/filter/sort/convert), "
        "JSON/XML (validate/format/analyze), "
        "code files (explain/review/fix/optimize/run/document/test), "
        "audio (transcribe/trim/convert/info), "
        "video (trim/extract_audio/extract_frame/compress/transcribe/info), "
        "archives (list/extract), "
        "presentations (summarize/extract_text). "
        "ALWAYS call this tool when a file has been uploaded and the user gives a command about it. "
        "If the user's command is ambiguous, pick the most logical action for that file type."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "file_path": {
                "type": "STRING",
                "description": "Full path to the uploaded file. Leave empty to use the currently uploaded file."
            },
            "action": {
                "type": "STRING",
                "description": (
                    "What to do with the file. Examples by type:\n"
                    "image: describe | ocr | resize | compress | convert | info\n"
                    "pdf: summarize | extract_text | to_word | info\n"
                    "docx/txt: summarize | fix | reformat | translate_hint | word_count | to_bullet\n"
                    "csv/excel: analyze | stats | filter | sort | convert | info\n"
                    "json: validate | format | analyze | to_csv\n"
                    "code: explain | review | fix | optimize | run | document | test\n"
                    "audio: transcribe | trim | convert | info\n"
                    "video: trim | extract_audio | extract_frame | compress | transcribe | info | convert\n"
                    "archive: list | extract\n"
                    "pptx: summarize | extract_text | analyze"
                )
            },
            "instruction": {
                "type": "STRING",
                "description": "Free-form instruction if action doesn't cover it. E.g. 'translate this to Turkish', 'find all email addresses'"
            },
            "format": {
                "type": "STRING",
                "description": "Target format for conversion. E.g. 'mp3', 'pdf', 'csv', 'png'"
            },
            "width":     {"type": "INTEGER", "description": "Target width for image resize"},
            "height":    {"type": "INTEGER", "description": "Target height for image resize"},
            "scale":     {"type": "NUMBER",  "description": "Scale factor for image resize (e.g. 0.5)"},
            "quality":   {"type": "INTEGER", "description": "Quality 1-100 for image/video compress"},
            "start":     {"type": "STRING",  "description": "Start time for trim: seconds or HH:MM:SS"},
            "end":       {"type": "STRING",  "description": "End time for trim: seconds or HH:MM:SS"},
            "timestamp": {"type": "STRING",  "description": "Timestamp for video frame extraction HH:MM:SS"},
            "column":    {"type": "STRING",  "description": "Column name for CSV filter/sort"},
            "value":     {"type": "STRING",  "description": "Filter value for CSV filter"},
            "condition": {"type": "STRING",  "description": "Filter condition: equals|contains|gt|lt"},
            "ascending": {"type": "BOOLEAN", "description": "Sort order for CSV sort (default: true)"},
            "save":      {"type": "BOOLEAN", "description": "Save result to file (default: true)"},
            "destination": {"type": "STRING", "description": "Output folder for archive extract"},
        },
        "required": []
    }
},
    {
        "name": "save_memory",
        "description": (
            "Save an important personal fact about the user to long-term memory. "
            "Call this silently whenever the user reveals something worth remembering: "
            "name, age, city, job, preferences, hobbies, relationships, projects, or future plans. "
            "Do NOT call for: weather, reminders, searches, or one-time commands. "
            "Do NOT announce that you are saving — just call it silently. "
            "Values must be in English regardless of the conversation language."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "category": {
                    "type": "STRING",
                    "description": (
                        "identity — name, age, birthday, city, job, language, nationality | "
                        "preferences — favorite food/color/music/film/game/sport, hobbies | "
                        "projects — active projects, goals, things being built | "
                        "relationships — friends, family, partner, colleagues | "
                        "wishes — future plans, things to buy, travel dreams | "
                        "notes — habits, schedule, anything else worth remembering"
                    )
                },
                "key":   {"type": "STRING", "description": "Short snake_case key (e.g. name, favorite_food, sister_name)"},
                "value": {"type": "STRING", "description": "Concise value in English (e.g. Fatih, pizza, older sister)"},
            },
            "required": ["category", "key", "value"]
        }
    },
    {
        "name": "gmail_processor",
        "description": (
            "Visible automation for Gmail. Use this for searching emails or drafting new ones. "
            "Action 'draft' will prepare the email in a visible window and wait for user review. "
            "Action 'send' will explicitly click the send button."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "search | draft | send"},
                "to": {"type": "STRING", "description": "Recipient email address"},
                "subject": {"type": "STRING", "description": "Email subject"},
                "body": {"type": "STRING", "description": "Email body content"},
                "query": {"type": "STRING", "description": "Search query"},
                "account_alias": {"type": "STRING", "description": "Which account to use (default: 'default')"}
            }
        }
    },
    {
        "name": "outlook_processor",
        "description": "Visible automation for Outlook. Supports 'search', 'draft', and 'send' actions.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "search | draft | send"},
                "to": {"type": "STRING"},
                "subject": {"type": "STRING"},
                "body": {"type": "STRING"},
                "query": {"type": "STRING"}
            }
        }
    },
    {
        "name": "github_processor",
        "description": "Visible automation for GitHub. Use for 'search' and 'draft_issue'.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "search | draft_issue"},
                "query": {"type": "STRING"},
                "repo": {"type": "STRING", "description": "Owner/Repo (e.g. 'google/playwright')"},
                "title": {"type": "STRING"},
                "body": {"type": "STRING"}
            }
        }
    },
    {
        "name": "system_status",
        "description": "Retrieves the system status (CPU, RAM, GPU, Network), activity logs, or controls UI visibility of GPU/Temperature.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "stats | logs | show_gpu | hide_gpu (default: stats)"}
            }
        }
    },
]

class JarvisLive:

    def __init__(self, ui: JarvisUI):
        self.ui             = ui
        self.ui._live_instance = self
        self.session        = None
        self.audio_in_queue = None
        self.out_queue      = None
        self._loop          = None
        self._is_speaking   = False
        self._speaking_lock = threading.Lock()
        self._reconnect_requested = False
        self.ui.on_text_command = self._on_text_command
        self.ui.on_speak        = self.speak
        self._turn_done_event: asyncio.Event | None = None
        self.session_history    = []

    def _on_text_command(self, text: str):
        if not self._loop or not self.session:
            return
        self.session_history.append(f"User: {text}")
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": text}]},
                turn_complete=True
            ),
            self._loop
        )

    def set_speaking(self, value: bool):
        with self._speaking_lock:
            self._is_speaking = value
        if value:
            self.ui.set_state("SPEAKING")
        elif not self.ui.muted:
            self.ui.set_state("LISTENING")

    def request_reconnect(self):
        self._reconnect_requested = True
        print("[JARVIS] 🔄 Reconnect requested...")

    def speak(self, text: str):
        if not self._loop or not self.session:
            return
        self.session_history.append(f"User (typed command): {text}")
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": text}]},
                turn_complete=True
            ),
            self._loop
        )

    def speak_error(self, tool_name: str, error: str):
        short = str(error)[:120]
        self.ui.write_log(f"ERR: {tool_name} — {short}")
        addr_pref = load_memory().get("preferences", {}).get("address_preference", {}).get("value", "sir")
        # Use only the first part of the preference if it contains 'or' (e.g. 'sir or the honored one' -> 'sir')
        short_addr = addr_pref.split(" or ")[0] if " or " in addr_pref else addr_pref
        self.speak(f"{short_addr.title()}, {tool_name} encountered an error. {short}")

    def _build_config(self) -> types.LiveConnectConfig:
        from datetime import datetime

        memory     = load_memory()
        mem_str    = format_memory_for_prompt(memory)
        sys_prompt = _load_system_prompt()

        now      = datetime.now()
        time_str = now.strftime("%A, %B %d, %Y — %I:%M %p")
        time_ctx = (
            f"[CURRENT DATE & TIME]\n"
            f"Right now it is: {time_str}\n"
            f"Use this to calculate exact times for reminders.\n\n"
        )

        parts = [time_ctx]
        if mem_str:
            parts.append(mem_str)
            
            # Explicitly call out addressing preference for emphasis
            addr_pref = memory.get("preferences", {}).get("address_preference", {}).get("value")
            if addr_pref:
                parts.append(f"\n[CRITICAL ADDRESSING RULE]\nYou must ONLY address the user as: {addr_pref}\n")
        
        parts.append(sys_prompt)

        parts.append("\n[DICTATION RULE]\nIf the user asks you to 'type this in for me' or dictate text, you MUST use the computer_control 'type' action. Normally, provide EXACTLY what the user said. However, if the user explicitly asks you to 'rewrite it professionally' or 'clean it up', you should remove filler words (like 'um', 'uh', 'like') and rewrite the text in a clean, polite, and professional manner before typing it. If they don't ask for a cleanup, just type the exact text requested.\n")

        # Inject recovered conversation history if we are reconnecting after a crash
        if self.session_history:
            parts.append("\n[RECENT CONVERSATION HISTORY (Recovered Context)]\n")
            parts.append("The Live API session was reconnected. Maintain context from the previous session history below:\n")
            history_str = "\n".join(self.session_history[-30:]) # Keep up to last 30 messages
            parts.append(history_str)
            parts.append("\n[END OF RECOVERED HISTORY]\n")

        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            input_audio_transcription={},
            system_instruction="\n".join(parts),
            tools=[{"function_declarations": TOOL_DECLARATIONS}],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=memory.get("settings", {}).get("active_voice", {}).get("value", "Charon")
                    )
                )
            ),
        )

    async def _execute_tool(self, fc) -> types.FunctionResponse:
        name = fc.name
        args = dict(fc.args or {})

        print(f"[JARVIS] 🔧 {name}  {args}")
        self.ui.set_state("THINKING")

        if name == "save_memory":
            category = args.get("category", "notes")
            key      = args.get("key", "")
            value    = args.get("value", "")
            if key and value:
                update_memory({category: {key: {"value": value}}})
                print(f"[Memory] 💾 save_memory: {category}/{key} = {value}")
            if not self.ui.muted:
                self.ui.set_state("LISTENING")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": "ok", "silent": True}
            )

        loop   = asyncio.get_event_loop()
        result = "Done."

        try:
            if name == "open_app":
                r = await loop.run_in_executor(None, lambda: open_app(parameters=args, response=None, player=self.ui))
                result = r or f"Opened {args.get('app_name')}."

            elif name == "weather_report":
                r = await loop.run_in_executor(None, lambda: weather_action(parameters=args, player=self.ui))
                result = r or "Weather delivered."

            elif name == "browser_control":
                r = await loop.run_in_executor(None, lambda: browser_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "file_controller":
                r = await loop.run_in_executor(None, lambda: file_controller(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "send_message":
                r = await loop.run_in_executor(None, lambda: send_message(parameters=args, response=None, player=self.ui, session_memory=None))
                result = r or f"Message sent to {args.get('receiver')}."

            elif name == "reminder":
                r = await loop.run_in_executor(None, lambda: reminder(parameters=args, response=None, player=self.ui))
                result = r or "Reminder set."

            elif name == "youtube_video":
                r = await loop.run_in_executor(None, lambda: youtube_video(parameters=args, response=None, player=self.ui))
                result = r or "Done."

            elif name == "screen_process":
                r = await loop.run_in_executor(
                    None, 
                    lambda: screen_process(parameters=args, response=None, player=self.ui, session_memory=None)
                )
                if r == False:
                    result = "Failed to process screen."
                else:
                    result = f"Vision result: {r}\n\n(Note: This is what the vision module saw. Respond naturally to the user's question using this information, and do NOT thank the user for the visual context because you looked at it yourself.)"

            elif name == "computer_settings":
                r = await loop.run_in_executor(None, lambda: computer_settings(parameters=args, response=None, player=self.ui))
                result = r or "Done."

            elif name == "desktop_control":
                r = await loop.run_in_executor(None, lambda: desktop_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "code_helper":
                r = await loop.run_in_executor(None, lambda: code_helper(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "dev_agent":
                r = await loop.run_in_executor(None, lambda: dev_agent(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "agent_task":
                from agent.task_queue import get_queue, TaskPriority
                priority_map = {"low": TaskPriority.LOW, "normal": TaskPriority.NORMAL, "high": TaskPriority.HIGH}
                priority = priority_map.get(args.get("priority", "normal").lower(), TaskPriority.NORMAL)
                task_id  = get_queue().submit(goal=args.get("goal", ""), priority=priority, speak=self.speak, deadline_minutes=args.get("deadline_minutes"))
                result   = f"Task started (ID: {task_id})."

            elif name == "timer":
                r = await loop.run_in_executor(None, lambda: timer_action(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "toggle_virtual_control":
                active = args.get("active", False)
                self.ui.set_virtual_control(active)
                result = f"Virtual hand control {'activated' if active else 'deactivated'}."

            elif name == "dock_camera_preview":
                self.ui.dock_camera_preview()
                result = "Camera preview docked back to the UI."

            elif name == "read_clipboard":
                r = await loop.run_in_executor(None, lambda: read_clipboard_action(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "web_search":
                r = await loop.run_in_executor(None, lambda: web_search_action(parameters=args, player=self.ui))
                result = r or "Done."
            elif name == "file_processor":
                if not args.get("file_path") and self.ui.current_file:
                    args["file_path"] = self.ui.current_file
                r = await loop.run_in_executor(
                    None,
                    lambda: file_processor(parameters=args, player=self.ui, speak=self.speak)
                )
                result = r or "Done."

            elif name == "computer_control":
                r = await loop.run_in_executor(None, lambda: computer_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "game_updater":
                r = await loop.run_in_executor(None, lambda: game_updater(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "flight_finder":
                r = await loop.run_in_executor(None, lambda: flight_finder(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "persona_control":
                r = await loop.run_in_executor(None, lambda: persona_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "gmail_processor":
                r = await loop.run_in_executor(None, lambda: gmail_processor(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "outlook_processor":
                r = await loop.run_in_executor(None, lambda: outlook_processor(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "github_processor":
                r = await loop.run_in_executor(None, lambda: github_processor(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "system_status":
                r = await loop.run_in_executor(None, lambda: system_status(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "shutdown_jarvis":
                self.ui.write_log("SYS: Shutdown requested.")
                addr_pref = load_memory().get("preferences", {}).get("address_preference", {}).get("value", "sir")
                short_addr = addr_pref.split(" or ")[0] if " or " in addr_pref else addr_pref
                self.speak(f"Goodbye, {short_addr}.")
                def _shutdown():
                    import time, os
                    time.sleep(1)
                    os._exit(0)
                threading.Thread(target=_shutdown, daemon=True).start()

            elif name == "restart_jarvis":
                self.ui.write_log("SYS: Restart requested.")
                addr_pref = load_memory().get("preferences", {}).get("address_preference", {}).get("value", "sir")
                self.speak(f"Restarting now, {addr_pref}.")
                def _restart():
                    import time, os, sys
                    time.sleep(1.5)
                    # Restart the process
                    os.execv(sys.executable, [sys.executable] + sys.argv)
                threading.Thread(target=_restart, daemon=True).start()

            else:
                result = f"Unknown tool: {name}"

        except Exception as e:
            traceback.print_exc()
            # ── Adaptive Vision Recovery ──────────────────────────
            # Capture screen and analyze what actually happened
            try:
                from core.vision_recovery import attempt_visual_recovery
                recovery = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda err=str(e): attempt_visual_recovery(
                        tool_name=name,
                        parameters=args,
                        error=err,
                        player=self.ui,
                    ),
                )
                diagnosis = recovery.get("diagnosis", str(e))
                actual    = recovery.get("actual_state", "unknown")
                corrected = recovery.get("corrected_params")
                # Give the LLM rich context so it can self-correct
                parts = [f"Tool '{name}' failed: {diagnosis}"]
                parts.append(f"Screen state: {actual}")
                if recovery.get("should_retry") and corrected:
                    parts.append(f"Suggested correction: {json.dumps(corrected, default=str)[:300]}")
                    parts.append("You may retry this tool with the corrected parameters.")
                result = " | ".join(parts)
                self.speak_error(name, diagnosis)
            except Exception:
                result = f"Tool '{name}' failed: {e}"
                self.speak_error(name, e)

        # ── Visual Verification for 'Soft Failures' ──────────────
        # If tool returns a string indicating failure, trigger vision recovery
        fail_keywords = ["couldn't find", "could not find", "error", "failed", "no results"]
        is_soft_fail = isinstance(result, str) and any(k in result.lower() for k in fail_keywords)
        
        if is_soft_fail and name in ("flight_finder", "browser_control", "web_search"):
            print(f"[JARVIS] 👁️ Result looks suspicious ('{result[:30]}...'), checking screen...")
            try:
                recovery = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: attempt_visual_recovery(
                        tool_name=name,
                        parameters=args,
                        error=str(result),
                        player=self.ui,
                    ),
                )
                if recovery.get("screenshot_taken"):
                    diagnosis = recovery.get("diagnosis", "")
                    actual    = recovery.get("actual_state", "")
                    if diagnosis:
                        result = f"{result} | Visual Analysis: {diagnosis} (Screen: {actual})"
            except Exception as ve:
                print(f"[JARVIS] ⚠️ Vision verification failed: {ve}")

        if not self.ui.muted:
            self.ui.set_state("LISTENING")

        print(f"[JARVIS] 📤 {name} → {str(result)[:80]}")
        return types.FunctionResponse(
            id=fc.id, name=name,
            response={"result": result}
        )

    async def _send_realtime(self):
        while True:
            msg = await self.out_queue.get()
            await self.session.send_realtime_input(audio=msg)

    async def _listen_audio(self):
        print("[JARVIS] 🎤 Mic started")
        loop = asyncio.get_event_loop()

        def _safe_enqueue(queue, item):
            try:
                queue.put_nowait(item)
            except asyncio.QueueFull:
                pass  # drop chunk silently — mic produces faster than network consumes

        def callback(indata, frames, time_info, status):
            with self._speaking_lock:
                jarvis_speaking = self._is_speaking
            if not jarvis_speaking and not self.ui.muted:
                data = indata.tobytes()
                loop.call_soon_threadsafe(
                    _safe_enqueue,
                    self.out_queue,
                    {"data": data, "mime_type": f"audio/pcm;rate={SEND_SAMPLE_RATE}"}
                )

        try:
            with sd.InputStream(
                samplerate=SEND_SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                blocksize=CHUNK_SIZE,
                callback=callback,
            ):
                print("[JARVIS] 🎤 Mic stream open")
                while True:
                    await asyncio.sleep(0.1)
        except Exception as e:
            print(f"[JARVIS] ❌ Mic: {e}")
            raise

    async def _receive_audio(self):
        print("[JARVIS] 👂 Recv started")
        out_buf, in_buf = [], []

        try:
            while True:
                async for response in self.session.receive():

                    if response.data:
                        if self._turn_done_event and self._turn_done_event.is_set():
                            self._turn_done_event.clear()
                        self.audio_in_queue.put_nowait(response.data)

                    if response.server_content:
                        sc = response.server_content

                        if sc.output_transcription and sc.output_transcription.text:
                            txt = _clean_transcript(sc.output_transcription.text)
                            if txt:
                                out_buf.append(txt)

                        if sc.input_transcription and sc.input_transcription.text:
                            txt = _clean_transcript(sc.input_transcription.text)
                            if txt:
                                in_buf.append(txt)

                        if sc.turn_complete:
                            if self._turn_done_event:
                                self._turn_done_event.set()

                            full_in = " ".join(in_buf).strip()
                            if full_in:
                                self.ui.write_log(f"You: {full_in}")
                                self.session_history.append(f"User: {full_in}")
                            in_buf = []

                            full_out = " ".join(out_buf).strip()
                            if full_out:
                                self.ui.write_log(f"Jarvis: {full_out}")
                                self.session_history.append(f"Jarvis: {full_out}")
                            out_buf = []

                    if response.tool_call:
                        fn_responses = []
                        for fc in response.tool_call.function_calls:
                            print(f"[JARVIS] 📞 {fc.name}")
                            fr = await self._execute_tool(fc)
                            fn_responses.append(fr)
                        await self.session.send_tool_response(
                            function_responses=fn_responses
                        )
        except Exception as e:
            print(f"[JARVIS] ❌ Recv: {e}")
            traceback.print_exc()
            raise

    async def _play_audio(self):
        print("[JARVIS] 🔊 Play started")

        stream = sd.RawOutputStream(
            samplerate=RECEIVE_SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=CHUNK_SIZE,
        )
        stream.start()

        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(
                        self.audio_in_queue.get(),
                        timeout=0.1
                    )
                except asyncio.TimeoutError:
                    if (
                        self._turn_done_event
                        and self._turn_done_event.is_set()
                        and self.audio_in_queue.empty()
                    ):
                        self.set_speaking(False)
                        self._turn_done_event.clear()
                    continue
                self.set_speaking(True)
                await asyncio.to_thread(stream.write, chunk)
        except Exception as e:
            print(f"[JARVIS] ❌ Play: {e}")
            raise
        finally:
            self.set_speaking(False)
            stream.stop()
            stream.close()

    async def run(self):
        client = genai.Client(
            api_key=_get_api_key(),
            http_options={"api_version": "v1beta"}
        )
        current_model = LIVE_MODEL

        while True:
            try:
                print(f"[JARVIS] 🔌 Connecting to {current_model}...")
                self.ui.set_state("THINKING")
                config = self._build_config()

                clean_model = current_model.replace("models/", "")
                async with (
                    client.aio.live.connect(model=clean_model, config=config) as session,
                    asyncio.TaskGroup() as tg,
                ):
                    self.session        = session
                    self._loop          = asyncio.get_event_loop()
                    self.audio_in_queue = asyncio.Queue()
                    self.out_queue      = asyncio.Queue(maxsize=10)
                    self._turn_done_event = asyncio.Event()

                    print("[JARVIS] ✅ Connected.")
                    self.ui.set_state("LISTENING")
                    self.ui.write_log("SYS: JARVIS online.")

                    tg.create_task(self._send_realtime())
                    tg.create_task(self._listen_audio())
                    tg.create_task(self._receive_audio())
                    tg.create_task(self._play_audio())

                    while not self._reconnect_requested:
                        await asyncio.sleep(0.5)
                    
                    self._reconnect_requested = False
                    raise ReconnectRequested()

            except ReconnectRequested:
                current_model = LIVE_MODEL
            except (Exception, ExceptionGroup, BaseExceptionGroup) as e:
                print(f"[JARVIS] ⚠️ {e}")
                traceback.print_exc()
                # Since we only use one model, we just sleep and retry the same model
                print(f"[JARVIS] ⚠️ Connection dropped. Reconnecting to {LIVE_MODEL}...")
                await asyncio.sleep(2)
            self.set_speaking(False)
            self.ui.set_state("THINKING")
            # If it was a forced reconnect, we don't need a long delay
            await asyncio.sleep(0.5)

def main():
    ui = JarvisUI("face.png")

    def runner():
        ui.wait_for_api_key()
        jarvis = JarvisLive(ui)
        try:
            asyncio.run(jarvis.run())
        except KeyboardInterrupt:
            print("\n🔴 Shutting down...")

    threading.Thread(target=runner, daemon=True).start()
    ui.root.mainloop()

if __name__ == "__main__":
    # ── Single-instance guard ────────────────────────────────────
    # Uses a Windows named mutex so only ONE Jarvis can run at a time.
    import ctypes
    _mutex = ctypes.windll.kernel32.CreateMutexW(None, True, "Global\\JarvisMark39SingleInstance")
    if ctypes.windll.kernel32.GetLastError() == 183:        # ERROR_ALREADY_EXISTS
        print("[JARVIS] ⚠️ Another instance is already running. Exiting.")
        ctypes.windll.kernel32.CloseHandle(_mutex)
        sys.exit(0)
    # ─────────────────────────────────────────────────────────────
    main()