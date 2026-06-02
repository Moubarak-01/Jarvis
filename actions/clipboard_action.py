try:
    import pyperclip
    _PYPERCLIP = True
except ImportError:
    _PYPERCLIP = False

def read_clipboard_action(parameters: dict, player=None, speak=None) -> str:
    text = ""
    if player and hasattr(player, "_clipboard_text") and player._clipboard_text:
        text = player._clipboard_text
    elif _PYPERCLIP:
        try:
            text = pyperclip.paste()
        except Exception:
            pass

    if not text:
        return "The clipboard is empty or could not be read."
    
    if len(text) >= 800:
        return f"[LONG_TEXT_PAYLOAD]\n{text}"
    
    # Just return the text to the model
    return f"Clipboard contents:\n\n{text}\n\n[SYSTEM INSTRUCTION: Please read the entire text above aloud completely, word for word, without stopping, summarizing, or skipping any parts.]"
