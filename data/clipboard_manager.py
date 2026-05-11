"""
ClipboardManager — reliable clipboard operations for automation workflows.

Provides:
  - Copy text to clipboard
  - Paste from clipboard
  - Save/restore clipboard state (to avoid corrupting user data)
  - Clipboard history (last N entries)
  - Format coercion (numbers, dates → strings)
"""

import time
import logging
from typing import Optional, Any
from collections import deque

import pyperclip

logger = logging.getLogger(__name__)


class ClipboardManager:
    """
    Manages clipboard operations with state preservation and history tracking.

    Usage:
        cb = ClipboardManager()

        with cb.preserve():
            cb.copy("Hello World")
            # ... paste via input controller ...
        # Original clipboard content is restored here
    """

    def __init__(self, history_size: int = 20):
        """
        Args:
            history_size: Number of clipboard entries to keep in history.
        """
        self._history: deque = deque(maxlen=history_size)
        self._saved_content: Optional[str] = None
        logger.info("ClipboardManager initialized (history_size=%d)", history_size)

    def copy(self, value: Any, delay: float = 0.05) -> str:
        """
        Copy a value to the clipboard.

        Automatically converts numbers, booleans, and other types to strings.

        Args:
            value: The value to copy (will be converted to str).
            delay: Brief pause after copying to ensure clipboard is ready.

        Returns:
            The string that was copied.
        """
        text = self._to_string(value)
        pyperclip.copy(text)
        time.sleep(delay)
        self._history.append(text)
        logger.debug("Clipboard set: %r (len=%d)", text[:50], len(text))
        return text

    def paste(self) -> str:
        """
        Read the current clipboard content.

        Returns:
            Current clipboard text.
        """
        content = pyperclip.paste()
        logger.debug("Clipboard read: %r (len=%d)", content[:50], len(content))
        return content

    def clear(self) -> None:
        """Clear the clipboard."""
        pyperclip.copy("")
        logger.debug("Clipboard cleared")

    def save(self) -> str:
        """
        Save the current clipboard content for later restoration.

        Returns:
            The saved content.
        """
        self._saved_content = pyperclip.paste()
        logger.debug("Clipboard saved: %r", self._saved_content[:50])
        return self._saved_content

    def restore(self) -> None:
        """Restore the previously saved clipboard content."""
        if self._saved_content is not None:
            pyperclip.copy(self._saved_content)
            logger.debug("Clipboard restored: %r", self._saved_content[:50])
        else:
            logger.debug("No saved clipboard content to restore")

    def get_history(self) -> list:
        """Return the clipboard history (most recent last)."""
        return list(self._history)

    def copy_and_verify(self, value: Any, max_attempts: int = 3) -> bool:
        """
        Copy a value and verify it was set correctly.

        Args:
            value: Value to copy.
            max_attempts: Number of copy attempts before giving up.

        Returns:
            True if clipboard matches the expected value, False otherwise.
        """
        expected = self._to_string(value)
        for attempt in range(1, max_attempts + 1):
            self.copy(expected)
            actual = self.paste()
            if actual == expected:
                return True
            logger.warning("Clipboard verify failed (attempt %d/%d): "
                           "expected %r, got %r",
                           attempt, max_attempts, expected[:30], actual[:30])
            time.sleep(0.1 * attempt)
        return False

    @staticmethod
    def _to_string(value: Any) -> str:
        """Convert any value to a clipboard-safe string."""
        if value is None:
            return ""
        if isinstance(value, bool):
            return "True" if value else "False"
        if isinstance(value, float):
            # Avoid scientific notation for large/small numbers
            if value == int(value):
                return str(int(value))
            return f"{value:.10g}"
        return str(value)

    class _PreserveContext:
        """Context manager that saves and restores clipboard content."""
        def __init__(self, manager: "ClipboardManager"):
            self._manager = manager

        def __enter__(self):
            self._manager.save()
            return self._manager

        def __exit__(self, *args):
            self._manager.restore()

    def preserve(self) -> "_PreserveContext":
        """
        Context manager to preserve and restore clipboard content.

        Usage:
            with clipboard.preserve():
                clipboard.copy("temp data")
                input_ctrl.paste()
            # Original clipboard is restored here
        """
        return self._PreserveContext(self)
