"""
Macro Recorder
==============
Records all mouse clicks, mouse movement, keyboard presses, and timing.
Saves to a JSON file that can be replayed by macro_player.py.

Events recorded:
  - mouse_move:    (x, y) absolute screen coordinates
  - mouse_click:   (x, y, button, pressed)
  - mouse_scroll:  (x, y, dx, dy)
  - key_press:     key name or character
  - key_release:   key name or character

Usage:
  recorder = MacroRecorder()
  recorder.start()          # begin recording
  # ... user performs task ...
  recorder.stop()           # stop recording
  recorder.save("my_macro") # save to macros/my_macro.json
"""

import os
import time
import json
import threading
import logging
from typing import List, Dict, Any, Optional, Callable

logger = logging.getLogger(__name__)

try:
    from pynput import mouse, keyboard
    _PYNPUT_AVAILABLE = True
except ImportError:
    _PYNPUT_AVAILABLE = False
    logger.warning("pynput not available — macro recording disabled")


class MacroRecorder:
    """
    Records mouse and keyboard events with precise timing.

    The recording captures:
      - Every mouse click (position + button)
      - Mouse movement (throttled to reduce file size)
      - Scroll wheel events
      - Every key press and release

    Timing is stored as elapsed seconds from the start of recording,
    so playback can reproduce the exact timing of the original actions.
    """

    MACROS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "macros")

    def __init__(self,
                 record_mouse_move: bool = True,
                 mouse_move_throttle_ms: float = 50.0,
                 on_event: Optional[Callable] = None):
        """
        Args:
            record_mouse_move: Whether to record mouse movement (increases file size).
            mouse_move_throttle_ms: Minimum ms between recorded move events.
            on_event: Optional callback(event_dict) called for each recorded event.
        """
        self.record_mouse_move = record_mouse_move
        self.mouse_move_throttle_ms = mouse_move_throttle_ms
        self.on_event = on_event

        self._events: List[Dict[str, Any]] = []
        self._start_time: float = 0.0
        self._recording: bool = False
        self._last_move_time: float = 0.0
        self._mouse_listener = None
        self._keyboard_listener = None
        self._lock = threading.Lock()

        os.makedirs(self.MACROS_DIR, exist_ok=True)

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        """Begin recording. Clears any previous recording."""
        if not _PYNPUT_AVAILABLE:
            raise RuntimeError("pynput is required for macro recording. Run install.bat.")

        with self._lock:
            self._events = []
            self._start_time = time.time()
            self._recording = True
            self._last_move_time = 0.0

        # Start listeners in daemon threads so they never block the GUI.
        # suppress=False means events still reach the target application.
        self._mouse_listener = mouse.Listener(
            on_move=self._on_move,
            on_click=self._on_click,
            on_scroll=self._on_scroll,
            daemon=True
        )
        self._keyboard_listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
            suppress=False,   # Don't consume keystrokes — let them reach the app
            daemon=True
        )
        self._mouse_listener.start()
        self._keyboard_listener.start()
        logger.info("Macro recording started")

    def stop(self) -> List[Dict[str, Any]]:
        """
        Stop recording and return the list of recorded events.

        IMPORTANT: listener.stop() blocks on Windows when called from the main
        thread. We signal _recording=False immediately (so no more events are
        captured) and then stop the listeners in a background daemon thread so
        the caller (tkinter main thread) is never blocked.
        """
        with self._lock:
            self._recording = False

        events_snapshot = list(self._events)
        logger.info("Macro recording stopped — %d events captured", len(events_snapshot))

        # Stop listeners in a background thread to avoid blocking the GUI
        ml = self._mouse_listener
        kl = self._keyboard_listener
        self._mouse_listener = None
        self._keyboard_listener = None

        def _stop_listeners():
            try:
                if ml:
                    ml.stop()
            except Exception:
                pass
            try:
                if kl:
                    kl.stop()
            except Exception:
                pass

        t = threading.Thread(target=_stop_listeners, daemon=True)
        t.start()

        return events_snapshot

    def save(self, name: str) -> str:
        """
        Save the recorded macro to a JSON file.

        Args:
            name: Macro name (used as filename, spaces replaced with underscores).

        Returns:
            Absolute path of the saved file.
        """
        safe_name = name.strip().replace(" ", "_").replace("/", "_")
        path = os.path.join(self.MACROS_DIR, f"{safe_name}.json")

        data = {
            "name": name,
            "version": "1.0",
            "recorded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "event_count": len(self._events),
            "duration_seconds": self._events[-1]["time"] if self._events else 0,
            "events": self._events
        }

        with open(path, "w") as f:
            json.dump(data, f, indent=2)

        logger.info("Macro saved: %s (%d events)", path, len(self._events))
        return path

    @classmethod
    def load(cls, name_or_path: str) -> Dict[str, Any]:
        """
        Load a macro from a JSON file.

        Args:
            name_or_path: Macro name (looks in macros/ dir) or full file path.

        Returns:
            Macro dict with 'name', 'events', etc.
        """
        if os.path.isabs(name_or_path) or name_or_path.endswith(".json"):
            path = name_or_path
        else:
            safe = name_or_path.strip().replace(" ", "_")
            path = os.path.join(cls.MACROS_DIR, f"{safe}.json")

        if not os.path.exists(path):
            raise FileNotFoundError(f"Macro not found: {path}")

        with open(path) as f:
            data = json.load(f)

        logger.info("Macro loaded: %s (%d events)", path, len(data.get("events", [])))
        return data

    @classmethod
    def list_macros(cls) -> List[Dict[str, str]]:
        """Return a list of saved macros with name and path."""
        os.makedirs(cls.MACROS_DIR, exist_ok=True)
        macros = []
        for filename in sorted(os.listdir(cls.MACROS_DIR)):
            if filename.endswith(".json"):
                path = os.path.join(cls.MACROS_DIR, filename)
                try:
                    with open(path) as f:
                        data = json.load(f)
                    macros.append({
                        "name": data.get("name", filename[:-5]),
                        "path": path,
                        "event_count": data.get("event_count", 0),
                        "duration": data.get("duration_seconds", 0),
                        "recorded_at": data.get("recorded_at", ""),
                    })
                except Exception:
                    pass
        return macros

    @property
    def event_count(self) -> int:
        return len(self._events)

    @property
    def is_recording(self) -> bool:
        return self._recording

    # ------------------------------------------------------------------ #
    #  Private Event Handlers                                              #
    # ------------------------------------------------------------------ #

    def _elapsed(self) -> float:
        return round(time.time() - self._start_time, 4)

    def _record(self, event: Dict[str, Any]) -> None:
        with self._lock:
            if self._recording:
                self._events.append(event)
                if self.on_event:
                    try:
                        self.on_event(event)
                    except Exception:
                        pass

    def _on_move(self, x: int, y: int) -> None:
        if not self.record_mouse_move:
            return
        now = time.time() * 1000
        if now - self._last_move_time < self.mouse_move_throttle_ms:
            return
        self._last_move_time = now
        self._record({"type": "mouse_move", "x": x, "y": y, "time": self._elapsed()})

    def _on_click(self, x: int, y: int, button, pressed: bool) -> None:
        self._record({
            "type": "mouse_click",
            "x": x, "y": y,
            "button": str(button).replace("Button.", ""),
            "pressed": pressed,
            "time": self._elapsed()
        })

    def _on_scroll(self, x: int, y: int, dx: int, dy: int) -> None:
        self._record({
            "type": "mouse_scroll",
            "x": x, "y": y, "dx": dx, "dy": dy,
            "time": self._elapsed()
        })

    def _on_key_press(self, key) -> None:
        self._record({
            "type": "key_press",
            "key": self._key_name(key),
            "time": self._elapsed()
        })

    def _on_key_release(self, key) -> None:
        self._record({
            "type": "key_release",
            "key": self._key_name(key),
            "time": self._elapsed()
        })

    @staticmethod
    def _key_name(key) -> str:
        try:
            return key.char  # Regular character
        except AttributeError:
            return str(key).replace("Key.", "")  # Special key like 'enter', 'ctrl'
