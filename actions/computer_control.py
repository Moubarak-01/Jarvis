#computer_control.py
import io
import json
import re
import string
import subprocess
import sys
import time
import random
import math
import os
import ctypes
from pathlib import Path
from memory.config_manager import get_gemini_key, get_os_system

try:
    import pyautogui
    pyautogui.FAILSAFE = False
    pyautogui.PAUSE    = 0.05
    _PYAUTOGUI = True
except ImportError:
    _PYAUTOGUI = False

try:
    import pyperclip
    _PYPERCLIP = True
except ImportError:
    _PYPERCLIP = False

try:
    import pygetwindow as gw
    _PYGETWINDOW = True
except ImportError:
    _PYGETWINDOW = False

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


_BASE         = _base_dir()
_MEMORY_PATH  = _BASE / "memory" / "long_term.json"
def _get_os() -> str:
    return get_os_system()

def _get_api_key() -> str:
    return get_gemini_key() or ""

_SAFE_SCREENSHOT_ROOTS = (
    Path.home(),
)

def _safe_screenshot_path(requested: str | None) -> Path:
    fallback = Path.home() / "Desktop" / "jarvis_screenshot.png"
    if not requested:
        return fallback
    try:
        p = Path(requested).expanduser().resolve()
        for root in _SAFE_SCREENSHOT_ROOTS:
            if p.is_relative_to(root.resolve()):
                p.parent.mkdir(parents=True, exist_ok=True)
                return p
    except Exception:
        pass
    return fallback

def _require_pyautogui():
    if not _PYAUTOGUI:
        raise RuntimeError("PyAutoGUI not installed. Run: pip install pyautogui")

_FIRST_NAMES = [
    "Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Drew", "Quinn",
    "Avery", "Blake", "Cameron", "Dakota", "Emerson", "Finley", "Harper",
]
_LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Wilson", "Moore", "Taylor", "Anderson", "Thomas", "Jackson",
]
_DOMAINS = ["gmail.com", "yahoo.com", "outlook.com", "proton.me", "mail.com"]


def _random_data(data_type: str) -> str:
    dt = data_type.lower().strip()

    if dt == "first_name":
        return random.choice(_FIRST_NAMES)

    if dt == "last_name":
        return random.choice(_LAST_NAMES)

    if dt == "name":
        return f"{random.choice(_FIRST_NAMES)} {random.choice(_LAST_NAMES)}"

    if dt == "email":
        first = random.choice(_FIRST_NAMES).lower()
        last  = random.choice(_LAST_NAMES).lower()
        num   = random.randint(10, 999)
        return f"{first}.{last}{num}@{random.choice(_DOMAINS)}"

    if dt == "username":
        return f"{random.choice(_FIRST_NAMES).lower()}{random.randint(100, 9999)}"

    if dt == "password":
        chars = string.ascii_letters + string.digits + "!@#$%"
        raw   = (
            random.choice(string.ascii_uppercase)
            + random.choice(string.digits)
            + random.choice("!@#$%")
            + "".join(random.choices(chars, k=9))
        )
        return "".join(random.sample(raw, len(raw)))

    if dt == "phone":
        return f"+1{random.randint(200,999)}{random.randint(1_000_000, 9_999_999)}"

    if dt == "birthday":
        y = random.randint(1980, 2000)
        m = random.randint(1, 12)
        d = random.randint(1, 28)
        return f"{m:02d}/{d:02d}/{y}"

    if dt == "address":
        num    = random.randint(100, 9999)
        street = random.choice(["Main St", "Oak Ave", "Park Blvd", "Elm St", "Cedar Ln"])
        return f"{num} {street}"

    if dt == "zip_code":
        return str(random.randint(10000, 99999))

    if dt == "city":
        return random.choice(["New York", "Los Angeles", "Chicago", "Houston", "Phoenix"])

    return f"random_{data_type}_{random.randint(1000, 9999)}"

def _user_profile() -> dict:
    """Read identity fields from long-term memory."""
    try:
        if _MEMORY_PATH.exists():
            data     = json.loads(_MEMORY_PATH.read_text(encoding="utf-8"))
            identity = data.get("identity", {})
            return {k: v.get("value", "") for k, v in identity.items()}
    except Exception:
        pass
    return {}

def _type(text: str, interval: float = 0.03) -> str:
    _require_pyautogui()
    time.sleep(0.3)
    pyautogui.typewrite(text, interval=interval)
    return f"Typed: {text[:60]}{'…' if len(text) > 60 else ''}"


def _smart_type(text: str, clear_first: bool = True) -> str:
    _require_pyautogui()
    if clear_first:
        _clear_field()
        time.sleep(0.1)

    if len(text) > 20 and _PYPERCLIP:
        pyperclip.copy(text)
        time.sleep(0.1)
        pyautogui.hotkey("ctrl", "v")
        return f"Smart-typed (clipboard): {text[:60]}{'…' if len(text) > 60 else ''}"

    pyautogui.typewrite(text, interval=0.04)
    return f"Smart-typed: {text[:60]}{'…' if len(text) > 60 else ''}"


def _click(x=None, y=None, button: str = "left", clicks: int = 1) -> str:
    _require_pyautogui()
    if x is not None and y is not None:
        pyautogui.click(x, y, button=button, clicks=clicks)
        return f"{'Double-c' if clicks == 2 else 'C'}licked ({x}, {y}) [{button}]"
    pyautogui.click(button=button, clicks=clicks)
    return f"Clicked at current position [{button}]"


def _hotkey(*keys) -> str:
    _require_pyautogui()
    pyautogui.hotkey(*keys)
    return f"Hotkey: {'+'.join(keys)}"


def _press(key: str) -> str:
    _require_pyautogui()
    pyautogui.press(key)
    return f"Pressed: {key}"


def _scroll(direction: str = "down", amount: int = 3) -> str:
    _require_pyautogui()
    vertical   = direction in ("up", "down")
    clicks     = amount if direction in ("up", "right") else -amount
    pyautogui.scroll(clicks) if vertical else pyautogui.hscroll(clicks)
    return f"Scrolled {direction} ×{amount}"


def _move(x: int, y: int, duration: float = 0.3) -> str:
    """Relative mouse movement — shifts cursor by (x, y) pixels from current position."""
    _require_pyautogui()
    pyautogui.move(x, y, duration=duration, tween=pyautogui.linear)
    return f"Mouse moved by ({x}, {y})"


def _move_to(x: int, y: int, duration: float = 0.3) -> str:
    """Absolute mouse movement — moves cursor to screen coordinate (x, y)."""
    _require_pyautogui()
    pyautogui.moveTo(x, y, duration=duration, tween=pyautogui.linear)
    return f"Mouse → ({x}, {y})"


def _circular_move(radius_px: int = 100, rotations: int = 1, duration: float = 2.0) -> str:
    """Move the mouse in a circle around its current position."""
    _require_pyautogui()
    cx, cy = pyautogui.position()
    steps = 60  # points per circle for smoothness
    total_steps = steps * rotations
    step_delay = duration / total_steps
    
    for i in range(total_steps + 1):
        angle = (2 * math.pi * i) / steps
        nx = cx + int(radius_px * math.cos(angle))
        ny = cy + int(radius_px * math.sin(angle))
        pyautogui.moveTo(nx, ny, _pause=False)
        time.sleep(step_delay)
    
    # Return to center
    pyautogui.moveTo(cx, cy, _pause=False)
    return f"Circular rotation: {rotations}x, radius={radius_px}px"


def _square_move(side_px: int = 100, rotations: int = 1, duration: float = 4.0) -> str:
    """Move the mouse in a square pattern around its current position."""
    return _rectangular_move(side_px, side_px, rotations, duration)


def _rectangular_move(width_px: int = 150, height_px: int = 100, rotations: int = 1, duration: float = 4.0) -> str:
    """Move the mouse in a rectangular pattern around its current position."""
    _require_pyautogui()
    cx, cy = pyautogui.position()
    
    tl_x = cx - width_px // 2
    tl_y = cy - height_px // 2
    
    pyautogui.moveTo(tl_x, tl_y, duration=0.2)
    time_per_side = duration / (4 * rotations)
    for _ in range(rotations):
        pyautogui.moveTo(tl_x + width_px, tl_y, duration=time_per_side, tween=pyautogui.linear)
        pyautogui.moveTo(tl_x + width_px, tl_y + height_px, duration=time_per_side, tween=pyautogui.linear)
        pyautogui.moveTo(tl_x, tl_y + height_px, duration=time_per_side, tween=pyautogui.linear)
        pyautogui.moveTo(tl_x, tl_y, duration=time_per_side, tween=pyautogui.linear)
        
    pyautogui.moveTo(cx, cy, duration=0.2)
    return f"Rectangular rotation: {rotations}x, w={width_px}px, h={height_px}px"


def _window_control(window_action: str, title: str) -> str:
    if not _PYGETWINDOW: return "pygetwindow not installed"
    
    if not title or title.lower() == "current":
        win = gw.getActiveWindow()
        if not win:
            return "No active window found."
    else:
        windows = gw.getWindowsWithTitle(title)
        if not windows: return f"No window found matching '{title}'"
        win = windows[0]
        
    try:
        if window_action == "minimize": win.minimize()
        elif window_action == "maximize": win.maximize()
        elif window_action == "restore": win.restore()
        elif window_action == "close": win.close()
        else: return f"Unknown window action: {window_action}"
        return f"Window '{win.title}' -> {window_action}"
    except Exception as e:
        return f"Window action failed: {e}"


def _list_windows() -> str:
    if not _PYGETWINDOW: return "pygetwindow not installed"
    titles = [w for w in gw.getAllTitles() if w.strip()]
    return "Open Windows:\n" + "\n".join(titles)


def _media_control(action: str) -> str:
    _require_pyautogui()
    keys = {
        "volumeup": "volumeup",
        "volumedown": "volumedown",
        "mute": "volumemute",
        "playpause": "playpause",
        "next": "nexttrack",
        "prev": "prevtrack",
        "space": "space"
    }
    if action not in keys: return f"Unknown media action: {action}"
    pyautogui.press(keys[action])
    return f"Media control: {action}"


def _lock_screen() -> str:
    if os.name == 'nt':
        ctypes.windll.user32.LockWorkStation()
        return "Screen locked."
    return "Lock screen only supported on Windows."


def _launch_app(app_name: str) -> str:
    if os.name == 'nt':
        os.system(f'start "" "{app_name}"')
        return f"Launched: {app_name}"
    return "App launching currently supported via OS native start."


def _draw_cursor_on_image(img_pil):
    try:
        import pyautogui
        import PIL.ImageDraw
        x, y = pyautogui.position()
        draw = PIL.ImageDraw.Draw(img_pil)
        r = 8  # radius of the red dot
        draw.ellipse([x-r, y-r, x+r, y+r], fill="red", outline="white", width=2)
    except Exception as e:
        print(f"[ComputerControl] Failed to draw cursor: {e}")
    return img_pil


def _read_screen_text() -> str:
    api_key = _get_api_key()
    if not api_key: return "No API key for screen reading."
    try:
        from google import genai
        _require_pyautogui()
        img = pyautogui.screenshot()
        img = _draw_cursor_on_image(img)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        image_bytes = buf.getvalue()
        
        prompt = "Read all the text visible in this screenshot. Reply with ONLY the extracted text, formatted nicely."
        from core.llm_helper import generate_content_with_waterfall
        import PIL.Image
        img_pil = PIL.Image.open(io.BytesIO(image_bytes))
        
        response = generate_content_with_waterfall([prompt, img_pil], is_vision=True)
        return (response.text or "").strip()
    except Exception as e:
        return f"read_screen_text failed: {e}"


def _drag(x1: int, y1: int, x2: int, y2: int, duration: float = 0.5) -> str:
    _require_pyautogui()
    pyautogui.moveTo(x1, y1, duration=0.2)
    pyautogui.dragTo(x2, y2, duration=duration, button="left")
    return f"Dragged ({x1},{y1}) → ({x2},{y2})"


def _clipboard_get() -> str:
    if _PYPERCLIP:
        return pyperclip.paste()
    _hotkey("ctrl", "c")
    time.sleep(0.2)
    return "(copied — pyperclip unavailable for read)"


def _clipboard_paste(text: str = "") -> str:
    """
    Pastes text via clipboard. 
    If text is provided, it overwrites the clipboard.
    If text is empty, it just performs a ctrl+v (preserving current clipboard).
    """
    if _PYPERCLIP:
        if text:
            pyperclip.copy(text)
            time.sleep(0.1) # Wait for OS clipboard to update
        
        _require_pyautogui()
        time.sleep(0.2) # Delay for focus stability
        pyautogui.hotkey("ctrl", "v")
        return f"Pasted: {text[:60] if text else '(system clipboard)'}{'…' if len(text) > 60 else ''}"
    return "pyperclip not available"


def _screenshot(save_path: str | None = None) -> str:
    _require_pyautogui()
    path = _safe_screenshot_path(save_path)
    img  = pyautogui.screenshot()
    img  = _draw_cursor_on_image(img)
    img.save(path)
    return f"Screenshot saved to {path}"


def _clear_field() -> str:
    _require_pyautogui()
    pyautogui.hotkey("ctrl", "a")
    time.sleep(0.1)
    pyautogui.press("delete")
    return "Field cleared"

def _focus_window(title: str) -> str:
    os_name = _get_os()

    if os_name == "windows":
        try:
            script = f'(New-Object -ComObject WScript.Shell).AppActivate("{title}")'
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True, timeout=5,
            )
            time.sleep(0.3)
            return f"Focused window: {title}"
        except Exception as e:
            return f"focus_window (Windows) failed: {e}"

    if os_name == "mac":
        script = (
            f'tell application "System Events" to '
            f'set frontmost of (first process whose name contains "{title}") to true'
        )
        try:
            subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, timeout=5,
            )
            time.sleep(0.3)
            return f"Focused window: {title}"
        except Exception as e:
            return f"focus_window (macOS) failed: {e}"

    if os_name == "linux":
        try:
            result = subprocess.run(
                ["wmctrl", "-a", title],
                capture_output=True, timeout=5,
            )
            if result.returncode == 0:
                time.sleep(0.3)
                return f"Focused window: {title}"
        except FileNotFoundError:
            pass
        try:
            result = subprocess.run(
                ["xdotool", "search", "--name", title, "windowactivate"],
                capture_output=True, timeout=5,
            )
            time.sleep(0.3)
            return f"Focused window: {title}"
        except FileNotFoundError:
            return "focus_window (Linux) requires wmctrl or xdotool"
        except Exception as e:
            return f"focus_window (Linux) failed: {e}"

    return f"focus_window: unknown OS '{os_name}'"

def _screen_find(description: str) -> tuple[int, int] | None:
    api_key = _get_api_key()
    if not api_key:
        print("[ComputerControl] ⚠️ No API key for screen_find")
        return None

    try:
        from google import genai
        from google.genai import types as gtypes

        _require_pyautogui()
        w, h  = pyautogui.size()
        img   = pyautogui.screenshot()
        img   = _draw_cursor_on_image(img)
        buf   = io.BytesIO()
        img.save(buf, format="PNG")
        image_bytes = buf.getvalue()

        cx, cy = pyautogui.position()

        client = genai.Client(api_key=api_key)
        prompt = (
            f"This is a screenshot of a {w}×{h} pixel screen. "
            f"The mouse cursor is currently located at X: {cx}, Y: {cy} (marked by the red dot). "
            f"Locate the UI element described as: '{description}'. "
            f"Reply with ONLY the center coordinates as: x,y "
            f"If the element is not visible, reply: NOT_FOUND"
        )

        from core.llm_helper import generate_content_with_waterfall
        import PIL.Image
        
        img_pil = PIL.Image.open(io.BytesIO(image_bytes))
        
        response = generate_content_with_waterfall(
            [prompt, img_pil],
            is_vision=True
        )

        text = (response.text or "").strip()
        if "NOT_FOUND" in text.upper():
            return None

        match = re.search(r"(\d+)\s*,\s*(\d+)", text)
        if match:
            return int(match.group(1)), int(match.group(2))

    except Exception as e:
        print(f"[ComputerControl] ⚠️ screen_find failed: {e}")

    return None

def computer_control(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """
    Dispatch table for all computer control actions.

    parameters keys (all optional unless noted):
      action        : (required) one of the actions listed below
      text          : text to type or paste
      x, y          : screen coordinates
      button        : 'left' | 'right' (default: left)
      keys          : hotkey string, e.g. 'ctrl+c'
      key           : single key name, e.g. 'enter'
      direction     : 'up' | 'down' | 'left' | 'right'
      amount        : scroll amount (default: 3)
      seconds       : wait duration
      title         : window title fragment for focus_window
      description   : natural-language element description for screen_find/click
      type          : data type for random_data
      field         : memory field name for user_data
      clear_first   : bool, clear field before typing (default: true)
      path          : save path for screenshot (must be inside home dir)

    Actions:
      type          — type text at cursor
      smart_type    — clear field + type (clipboard-backed)
      click         — left click
      double_click  — double left click
      right_click   — right click
      move          — move mouse
      drag          — click-drag between two points
      hotkey        — key combination
      press         — single key
      scroll        — scroll the wheel
      copy          — read clipboard
      paste         — write + paste clipboard
      screenshot    — capture screen (safe path only)
      wait          — sleep N seconds
      clear_field   — select-all + delete
      focus_window  — bring window to foreground
      screen_find   — AI element finder (returns x,y)
      screen_click  — AI element finder + click
      random_data   — generate fake form data
      user_data     — pull real data from memory
    """
    params = parameters or {}
    action = params.get("action", "").lower().strip()

    if not action:
        return "No action specified for computer_control."

    if player:
        player.write_log(f"[Computer] {action}")

    print(f"[ComputerControl] ▶ {action}  {params}")

    try:

        if action == "type":
            return _type(params.get("text", ""))

        if action == "smart_type":
            return _smart_type(
                params.get("text", ""),
                clear_first=params.get("clear_first", True),
            )

        if action in ("click", "left_click"):
            return _click(params.get("x"), params.get("y"), "left", 1)

        if action == "double_click":
            return _click(params.get("x"), params.get("y"), "left", 2)

        if action == "right_click":
            return _click(params.get("x"), params.get("y"), "right", 1)

        if action == "move":
            x = int(params.get("x", 0))
            y = int(params.get("y", 0))
            direction = params.get("direction", "").lower()
            if direction:
                val = int(params.get("amount", 0)) or abs(x) or abs(y) or 50
                if direction == "left":
                    x, y = -abs(val), 0
                elif direction == "right":
                    x, y = abs(val), 0
                elif direction == "up":
                    x, y = 0, -abs(val)
                elif direction == "down":
                    x, y = 0, abs(val)
            return _move(x, y)

        if action == "move_to":
            return _move_to(int(params.get("x", 0)), int(params.get("y", 0)))

        if action == "circular_move":
            return _circular_move(
                radius_px=int(params.get("radius", 100)),
                rotations=int(params.get("rotations", 1)),
                duration=float(params.get("duration", 2.0)),
            )

        if action == "square_move":
            return _square_move(
                side_px=int(params.get("side", 100)),
                rotations=int(params.get("rotations", 1)),
                duration=float(params.get("duration", 2.0)),
            )

        if action == "rectangular_move":
            return _rectangular_move(
                width_px=int(params.get("width", 150)),
                height_px=int(params.get("height", 100)),
                rotations=int(params.get("rotations", 1)),
                duration=float(params.get("duration", 2.0)),
            )

        if action == "window_control":
            return _window_control(params.get("window_action", ""), params.get("title", ""))

        if action == "list_windows":
            return _list_windows()

        if action == "media_control":
            return _media_control(params.get("media_action", ""))

        if action == "lock_screen":
            return _lock_screen()

        if action == "launch_app":
            return _launch_app(params.get("app_name", ""))

        if action == "read_screen_text":
            return _read_screen_text()

        if action == "drag":
            return _drag(
                int(params.get("x1", 0)), int(params.get("y1", 0)),
                int(params.get("x2", 0)), int(params.get("y2", 0)),
            )

        if action == "hotkey":
            raw  = params.get("keys", "")
            keys = [k.strip() for k in raw.split("+")] if isinstance(raw, str) else raw
            return _hotkey(*keys)

        if action == "press":
            return _press(params.get("key", "enter"))

        if action == "scroll":
            return _scroll(
                direction=params.get("direction", "down"),
                amount=int(params.get("amount", 3)),
            )

        if action == "copy":
            return _clipboard_get()

        if action == "paste":
            return _clipboard_paste(params.get("text", ""))

        if action == "screenshot":
            return _screenshot(params.get("path"))

        if action == "screen_find":
            coords = _screen_find(params.get("description", ""))
            return f"{coords[0]},{coords[1]}" if coords else "NOT_FOUND"

        if action == "screen_click":
            desc   = params.get("description", "")
            coords = _screen_find(desc)
            if coords:
                time.sleep(0.2)
                _click(x=coords[0], y=coords[1])
                return f"Clicked '{desc}' at {coords}"
            return f"Element not found on screen: '{desc}'"

        if action == "screen_double_click":
            desc   = params.get("description", "")
            coords = _screen_find(desc)
            if coords:
                time.sleep(0.2)
                _click(x=coords[0], y=coords[1], clicks=2)
                return f"Double-clicked '{desc}' at {coords}"
            return f"Element not found on screen: '{desc}'"

        if action == "screen_right_click":
            desc   = params.get("description", "")
            coords = _screen_find(desc)
            if coords:
                time.sleep(0.2)
                _click(x=coords[0], y=coords[1], button="right")
                return f"Right-clicked '{desc}' at {coords}"
            return f"Element not found on screen: '{desc}'"

        if action == "wait":
            secs = float(params.get("seconds", 1.0))
            secs = min(secs, 30.0)
            time.sleep(secs)
            return f"Waited {secs}s"

        if action == "clear_field":
            return _clear_field()

        if action == "focus_window":
            return _focus_window(params.get("title", ""))

        if action == "random_data":
            dt     = params.get("type", "name")
            result = _random_data(dt)
            print(f"[ComputerControl] 🎲 random {dt} → {result}")
            return result

        if action == "user_data":
            field   = params.get("field", "name")
            profile = _user_profile()
            value   = profile.get(field, "")
            if not value:
                value = _random_data(field)
                print(f"[ComputerControl] ⚠️ No '{field}' in memory, using random: {value}")
            return value

        return f"Unknown action: '{action}'"

    except Exception as e:
        print(f"[ComputerControl] ❌ {action}: {e}")
        return f"computer_control '{action}' failed: {e}"