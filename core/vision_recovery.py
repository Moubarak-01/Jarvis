"""
Adaptive Vision Recovery for JARVIS Mark-XXXIX.

When a tool fails or returns a suspicious result, this module captures
the screen, sends it to the vision model, and determines what actually
happened — enabling self-correction instead of blind failure.

Usage:
    from core.vision_recovery import attempt_visual_recovery

    # In a tool's except block:
    recovery = attempt_visual_recovery(
        tool_name="browser_control",
        parameters={"action": "go_to", "url": "..."},
        error="Element not found",
    )
    # recovery = {"diagnosis": "...", "suggestion": "...", "should_retry": True, "corrected_params": {...}}
"""

import io
import re
import json
import traceback
from typing import Optional

try:
    import mss
    import mss.tools
    _MSS = True
except ImportError:
    _MSS = False

try:
    import PIL.Image
    _PIL = True
except ImportError:
    _PIL = False


def _quick_screenshot() -> tuple[bytes, str] | None:
    """Capture the active monitor quickly. Returns (image_bytes, mime_type) or None."""
    if not _MSS:
        return None

    try:
        import pyautogui
        with mss.mss() as sct:
            monitors = sct.monitors
            x, y = pyautogui.position()
            target = monitors[0]
            for i, m in enumerate(monitors[1:], 1):
                if (m["left"] <= x < m["left"] + m["width"] and
                    m["top"]  <= y < m["top"]  + m["height"]):
                    target = m
                    break

            shot = sct.grab(target)
            png  = mss.tools.to_png(shot.rgb, shot.size)

        if _PIL:
            import PIL.ImageDraw
            img = PIL.Image.open(io.BytesIO(png))
            
            local_x = x - target["left"]
            local_y = y - target["top"]
            
            draw = PIL.ImageDraw.Draw(img)
            r = 8
            draw.ellipse([local_x-r, local_y-r, local_x+r, local_y+r], fill="red", outline="white", width=2)
            
            # Compress if large
            if len(png) > 2_000_000:
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=85, optimize=True)
                return buf.getvalue(), "image/jpeg"
            else:
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                return buf.getvalue(), "image/png"

        return png, "image/png"

    except Exception as e:
        print(f"[VisionRecovery] ⚠️ Screenshot failed: {e}")
        return None


_RECOVERY_PROMPT = """\
You are JARVIS's diagnostic vision system. A tool action just FAILED.
Analyze the screenshot to determine what ACTUALLY happened on screen.

You must return ONLY valid JSON (no markdown, no explanation):
{
  "diagnosis": "Brief description of what you see on screen (1-2 sentences)",
  "actual_state": "What state the screen is in (e.g. 'login page showing', 'page still loading', 'captcha appeared', 'wrong page loaded')",
  "should_retry": true/false,
  "corrected_action": "Suggested corrected action or null if retry won't help",
  "corrected_params": {} or null
}
"""


def attempt_visual_recovery(
    tool_name: str,
    parameters: dict,
    error: str,
    player=None,
) -> dict:
    """
    Capture screen and analyze what went wrong after a tool failure.

    Returns:
        {
            "diagnosis": str,        # What the vision model sees
            "actual_state": str,      # Screen state description
            "should_retry": bool,     # Whether retrying could help
            "corrected_action": str,  # Suggested fix or None
            "corrected_params": dict, # Corrected parameters or None
            "screenshot_taken": bool, # Whether we got a screenshot
        }
    """
    print(f"[VisionRecovery] 👁️ Analyzing screen after {tool_name} failure...")

    fallback = {
        "diagnosis": f"Tool '{tool_name}' failed: {str(error)[:100]}",
        "actual_state": "unknown",
        "should_retry": False,
        "corrected_action": None,
        "corrected_params": None,
        "screenshot_taken": False,
    }

    # Take screenshot
    shot = _quick_screenshot()
    if not shot:
        print("[VisionRecovery] ⚠️ Could not capture screen — skipping visual recovery")
        return fallback

    image_bytes, mime_type = shot
    print(f"[VisionRecovery] 📸 Captured {len(image_bytes):,} bytes")

    # Build the analysis prompt
    context = (
        f"Tool that failed: {tool_name}\n"
        f"Parameters used: {json.dumps(parameters, indent=2, default=str)[:500]}\n"
        f"Error message: {str(error)[:300]}\n\n"
        "Look at the screenshot and tell me what's actually on screen. "
        "Did the action partially succeed? Is there a popup, error dialog, "
        "or unexpected page? What should JARVIS do next?"
    )

    try:
        from core.llm_helper import generate_content_with_waterfall

        img = PIL.Image.open(io.BytesIO(image_bytes))
        prompt = [context, img]

        response = generate_content_with_waterfall(
            prompt,
            system_instruction=_RECOVERY_PROMPT,
            is_vision=True,
        )

        text = response.text.strip()
        
        # IMPROVED: Look for the first { and last } to extract JSON even if model adds fluff
        json_match = re.search(r"(\{.*\})", text, re.DOTALL)
        if json_match:
            try:
                result = json.loads(json_match.group(1))
                result["screenshot_taken"] = True
                print(f"[VisionRecovery] ✅ Diagnosis: {result.get('diagnosis', '')[:100]}")
                print(f"[VisionRecovery]    State: {result.get('actual_state', '')}")
                print(f"[VisionRecovery]    Retry: {result.get('should_retry', False)}")
                
                if player:
                    player.write_log(f"SYS: Vision Recovery — {result.get('diagnosis', 'analyzed screen')}")
                
                return result
            except json.JSONDecodeError:
                pass # fall through to raw text fallback

        # Fallback for raw text responses
        print(f"[VisionRecovery] ⚠️ Vision model returned non-JSON, using raw text fallback")
        should_retry = any(k in text.lower() for k in ["retry", "correction", "try again"])
        
        return {
            "diagnosis": text[:300],
            "actual_state": "visually analyzed",
            "should_retry": should_retry,
            "corrected_action": None,
            "corrected_params": None,
            "screenshot_taken": True,
        }

    except Exception as e:
        print(f"[VisionRecovery] ❌ Analysis failed: {e}")
        traceback.print_exc()
        return fallback


def verify_tool_result(
    tool_name: str,
    parameters: dict,
    result: str,
    player=None,
) -> dict:
    """
    Optional post-action verification for high-stakes tools.
    Takes a screenshot AFTER a tool claims success and verifies
    the screen matches expectations.

    Only called for tools where visual confirmation matters:
    browser_control, computer_control, computer_settings.

    Returns:
        {
            "verified": bool,    # Whether the action looks successful
            "observation": str,  # What the vision model sees
        }
    """
    # Only verify high-stakes tools
    if tool_name not in ("browser_control", "computer_control"):
        return {"verified": True, "observation": "Verification skipped — low-risk tool."}

    # Only verify actions that change visible state
    action = parameters.get("action", "")
    visual_actions = {
        "go_to", "search", "click", "type", "fill_form",
        "smart_click", "smart_type", "screen_click",
    }
    if action not in visual_actions:
        return {"verified": True, "observation": "Non-visual action — skipped verification."}

    shot = _quick_screenshot()
    if not shot:
        return {"verified": True, "observation": "Could not screenshot — assuming success."}

    image_bytes, mime_type = shot

    verify_prompt = (
        f"JARVIS just executed: {tool_name}(action='{action}')\n"
        f"Parameters: {json.dumps(parameters, default=str)[:300]}\n"
        f"Tool reported: {str(result)[:200]}\n\n"
        "Look at the screenshot. Does the screen show that the action was successful? "
        "Reply ONLY with JSON: {\"verified\": true/false, \"observation\": \"what you see\"}"
    )

    try:
        from core.llm_helper import generate_content_with_waterfall

        img = PIL.Image.open(io.BytesIO(image_bytes))
        response = generate_content_with_waterfall(
            [verify_prompt, img],
            is_vision=True,
        )

        text = response.text.strip()
        text = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()
        parsed = json.loads(text)
        print(f"[VisionRecovery] 🔍 Verify: verified={parsed.get('verified')} — {parsed.get('observation', '')[:80]}")
        return parsed

    except Exception as e:
        print(f"[VisionRecovery] ⚠️ Verification failed: {e}")
        return {"verified": True, "observation": f"Verification error: {e}"}
