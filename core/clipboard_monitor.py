"""
Clipboard Monitor for JARVIS Mark-XXXIX.

Watches the system clipboard and suggests smart actions when content
is copied. Always uses suggest-and-confirm — never auto-acts.

Integrates with PyQt6's clipboard system via QApplication.clipboard().
"""

import re
import time
from typing import Optional, Callable

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication


# ── Content classification patterns ──────────────────────
_URL_RE     = re.compile(r"https?://\S+", re.IGNORECASE)
_EMAIL_RE   = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_PHONE_RE   = re.compile(r"[\+]?[(]?\d{1,4}[)]?[-\s\./\d]{6,15}")
_PATH_RE    = re.compile(r"^[A-Za-z]:\\(?:[^\\/:*?\"<>|\r\n]+\\)*[^\\/:*?\"<>|\r\n]*$", re.MULTILINE)
_CODE_HINTS = re.compile(
    r"(def\s+\w+|class\s+\w+|import\s+\w+|function\s+\w+|const\s+\w+|"
    r"let\s+\w+|var\s+\w+|public\s+\w+|#include|System\.\w+|\{[^}]+\})",
    re.MULTILINE,
)


def classify_content(text: str) -> Optional[str]:
    """
    Classify clipboard text into a content type.
    Returns: 'url', 'email', 'phone', 'path', 'code', 'long_text', or None.
    """
    text = text.strip()
    if not text or len(text) < 3:
        return None

    # Short content (< 10 chars) is too ambiguous
    if len(text) < 10 and not _EMAIL_RE.search(text):
        return None

    # Check in priority order
    if _URL_RE.search(text):
        return "url"

    if _EMAIL_RE.search(text):
        return "email"

    if _PATH_RE.search(text):
        return "path"

    # Code detection — needs multiple signals
    code_matches = _CODE_HINTS.findall(text)
    if len(code_matches) >= 2 or (len(text) > 30 and len(code_matches) >= 1):
        return "code"

    if _PHONE_RE.search(text) and len(text) < 25:
        return "phone"

    # Long text — offer to summarize
    if len(text) > 200:
        return "long_text"

    return None


# ── Suggestion mapping ───────────────────────────────────
_SUGGESTIONS = {
    "url":       ("🔗", "I noticed you copied a URL. Want me to open or summarize this link?"),
    "email":     ("📧", "I see an email address. Want me to draft an email to this person?"),
    "phone":     ("📱", "I see a phone number. Want me to save this contact?"),
    "path":      ("📂", "I see a file path. Want me to open this file?"),
    "code":      ("💻", "I see some code. Want me to explain or run this?"),
    "long_text": ("📝", "I see a long text. Want me to summarize this?"),
}


class ClipboardMonitor(QObject):
    """
    Monitors the system clipboard for interesting content and emits
    suggestions. Debounced and deduped to avoid spam.

    Signals:
        suggestion(str, str, str) — (content_type, suggestion_text, clipboard_text)
    """
    suggestion = pyqtSignal(str, str, str)  # content_type, message, raw_text

    def __init__(self, parent=None):
        super().__init__(parent)
        self._enabled      = True
        self._last_text    = ""
        self._last_suggest = 0.0
        self._debounce_ms  = 500   # Wait 500ms after last change before processing
        self._cooldown_s   = 5.0   # Min 5s between suggestions

        self._clipboard = QApplication.clipboard()
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self._process_clipboard)

        # Connect to clipboard change signal
        self._clipboard.dataChanged.connect(self._on_clipboard_change)
        print("[Clipboard] 📋 Monitor started")

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        self._enabled = value
        state = "enabled" if value else "disabled"
        print(f"[Clipboard] 📋 Monitor {state}")

    def _on_clipboard_change(self):
        """Called when clipboard content changes. Starts debounce timer."""
        if not self._enabled:
            return
        # Restart debounce timer — only process after clipboard settles
        self._debounce_timer.start(self._debounce_ms)

    def _process_clipboard(self):
        """Process clipboard after debounce period."""
        if not self._enabled:
            return

        text = self._clipboard.text()
        if not text or not text.strip():
            return

        text = text.strip()

        # Skip if same as last processed text (dedup)
        if text == self._last_text:
            return

        # Skip if too soon after last suggestion (cooldown)
        now = time.time()
        if now - self._last_suggest < self._cooldown_s:
            return

        # Classify and suggest
        content_type = classify_content(text)
        if content_type is None:
            return

        icon, message = _SUGGESTIONS.get(content_type, ("📋", "Interesting clipboard content."))
        full_message = f"{icon}  {message}"

        # Update state
        self._last_text    = text
        self._last_suggest = now

        # Emit signal for the UI to display
        preview = text[:80] + ("..." if len(text) > 80 else "")
        print(f"[Clipboard] 📋 Detected {content_type}: {preview}")

        self.suggestion.emit(content_type, full_message, text)
