"""
InputController — wraps pyautogui for all mouse and keyboard operations.

Provides a safe, logged, configurable interface to:
  - Move and click the mouse
  - Type text and press keys
  - Drag and scroll
  - Hotkey combinations
  - Clipboard-based paste (for speed and special characters)
"""

import os
import time
import logging
import pyperclip

# Suppress pyautogui's mouseinfo import error in headless environments
os.environ.setdefault("DISPLAY", ":99")

import pyautogui

logger = logging.getLogger(__name__)

# Safety configuration
pyautogui.FAILSAFE = True          # Move mouse to top-left corner to abort
pyautogui.PAUSE = 0.05             # Default pause between actions (seconds)


class InputController:
    """
    Provides a unified, safe interface for all mouse and keyboard input.

    All methods are logged at DEBUG level. Errors are propagated to the
    caller so the workflow engine can handle them appropriately.
    """

    def __init__(self, typing_interval: float = 0.03, move_duration: float = 0.2):
        self.typing_interval = typing_interval
        self.move_duration = move_duration
        logger.info("InputController initialized (typing_interval=%.3f, move_duration=%.3f)",
                    typing_interval, move_duration)

    # ------------------------------------------------------------------ #
    #  Mouse Operations                                                    #
    # ------------------------------------------------------------------ #

    def move_to(self, x: int, y: int, duration: float = None) -> None:
        """Move the mouse cursor to absolute screen coordinates."""
        dur = duration if duration is not None else self.move_duration
        logger.debug("Mouse move → (%d, %d) over %.2fs", x, y, dur)
        pyautogui.moveTo(x, y, duration=dur)

    def click(self, x: int = None, y: int = None, button: str = "left",
              clicks: int = 1, interval: float = 0.1) -> None:
        """Click at (x, y) or at the current cursor position."""
        if x is not None and y is not None:
            logger.debug("Click %s (%d, %d) x%d", button, x, y, clicks)
            pyautogui.click(x, y, button=button, clicks=clicks, interval=interval)
        else:
            logger.debug("Click %s at current position x%d", button, clicks)
            pyautogui.click(button=button, clicks=clicks, interval=interval)

    def double_click(self, x: int = None, y: int = None) -> None:
        """Double-click at (x, y) or at the current cursor position."""
        logger.debug("Double-click at (%s, %s)", x, y)
        if x is not None and y is not None:
            pyautogui.doubleClick(x, y)
        else:
            pyautogui.doubleClick()

    def right_click(self, x: int = None, y: int = None) -> None:
        """Right-click at (x, y) or at the current cursor position."""
        logger.debug("Right-click at (%s, %s)", x, y)
        if x is not None and y is not None:
            pyautogui.rightClick(x, y)
        else:
            pyautogui.rightClick()

    def drag_to(self, x: int, y: int, duration: float = 0.5,
                button: str = "left") -> None:
        """Click and drag from the current position to (x, y)."""
        logger.debug("Drag to (%d, %d) over %.2fs", x, y, duration)
        pyautogui.dragTo(x, y, duration=duration, button=button)

    def scroll(self, clicks: int, x: int = None, y: int = None) -> None:
        """Scroll the mouse wheel. Positive = up, negative = down."""
        logger.debug("Scroll %+d at (%s, %s)", clicks, x, y)
        if x is not None and y is not None:
            pyautogui.scroll(clicks, x=x, y=y)
        else:
            pyautogui.scroll(clicks)

    def get_position(self) -> tuple:
        """Return the current (x, y) mouse position."""
        pos = pyautogui.position()
        logger.debug("Mouse position: %s", pos)
        return pos

    # ------------------------------------------------------------------ #
    #  Keyboard Operations                                                 #
    # ------------------------------------------------------------------ #

    def type_text(self, text: str, interval: float = None) -> None:
        """Type a string character by character."""
        ivl = interval if interval is not None else self.typing_interval
        logger.debug("Typing text (len=%d, interval=%.3f)", len(text), ivl)
        pyautogui.typewrite(text, interval=ivl)

    def type_text_clipboard(self, text: str) -> None:
        """
        Paste text via clipboard — faster than typewrite and handles
        special characters, Unicode, and long strings reliably.
        """
        logger.debug("Clipboard-paste text (len=%d)", len(text))
        original = pyperclip.paste()
        pyperclip.copy(text)
        time.sleep(0.05)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.1)
        # Restore original clipboard content
        pyperclip.copy(original)

    def press_key(self, key: str) -> None:
        """Press and release a single key (e.g. 'enter', 'tab', 'esc')."""
        logger.debug("Key press: %s", key)
        pyautogui.press(key)

    def hotkey(self, *keys: str) -> None:
        """Press a hotkey combination (e.g. hotkey('ctrl', 'c'))."""
        logger.debug("Hotkey: %s", "+".join(keys))
        pyautogui.hotkey(*keys)

    def key_down(self, key: str) -> None:
        """Hold a key down."""
        logger.debug("Key down: %s", key)
        pyautogui.keyDown(key)

    def key_up(self, key: str) -> None:
        """Release a held key."""
        logger.debug("Key up: %s", key)
        pyautogui.keyUp(key)

    def tab(self, count: int = 1) -> None:
        """Press Tab key one or more times (for field navigation)."""
        for _ in range(count):
            self.press_key("tab")
            time.sleep(0.05)

    def enter(self) -> None:
        """Press the Enter key."""
        self.press_key("enter")

    def escape(self) -> None:
        """Press the Escape key."""
        self.press_key("escape")

    def select_all(self) -> None:
        """Select all text in the current field (Ctrl+A)."""
        self.hotkey("ctrl", "a")

    def clear_field(self) -> None:
        """Select all and delete — clears the current input field."""
        self.select_all()
        time.sleep(0.05)
        self.press_key("delete")

    def copy(self) -> str:
        """Copy selected content to clipboard and return it."""
        self.hotkey("ctrl", "c")
        time.sleep(0.1)
        return pyperclip.paste()

    def paste(self) -> None:
        """Paste clipboard content."""
        self.hotkey("ctrl", "v")

    # ------------------------------------------------------------------ #
    #  Utility                                                             #
    # ------------------------------------------------------------------ #

    def sleep(self, seconds: float) -> None:
        """Pause execution for a given number of seconds."""
        logger.debug("Sleep %.2fs", seconds)
        time.sleep(seconds)

    def set_typing_speed(self, interval: float) -> None:
        """Adjust the per-character typing delay."""
        self.typing_interval = interval
        logger.info("Typing interval set to %.3f", interval)

    def set_move_speed(self, duration: float) -> None:
        """Adjust the mouse movement duration."""
        self.move_duration = duration
        logger.info("Move duration set to %.3f", duration)
