"""
Macro Player
============
Replays a recorded macro (from macro_recorder.py) with configurable:
  - Speed multiplier (0.5 = half speed, 2.0 = double speed, 0 = no delays)
  - Repeat count (play N times)
  - Stop event (thread-safe cancel at any point)

Usage:
    player = MacroPlayer()
    player.play("my_macro", speed=1.0, repeat=1)

    # Or with a stop event for GUI integration:
    stop_event = threading.Event()
    player.play("my_macro", stop_event=stop_event)
    # ... later ...
    stop_event.set()  # stops playback
"""

import os
import time
import json
import threading
import logging
from typing import Optional, Callable, Dict, Any, List

logger = logging.getLogger(__name__)

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0
    _PYAUTOGUI_AVAILABLE = True
except ImportError:
    _PYAUTOGUI_AVAILABLE = False
    logger.warning("pyautogui not available — macro playback disabled")

from macro_recorder import MacroRecorder


class MacroPlayer:
    """
    Replays recorded macros by executing each event in sequence.

    Supports:
      - Speed multiplier: scale all delays (1.0 = original speed)
      - Repeat: play the macro N times
      - Stop event: cancel playback at any time
      - Progress callback: called after each event
    """

    def __init__(self):
        self._playing = False
        self._stop_event: Optional[threading.Event] = None

    @property
    def is_playing(self) -> bool:
        return self._playing

    def play(self,
             macro: Any,
             speed: float = 1.0,
             repeat: int = 1,
             stop_event: Optional[threading.Event] = None,
             progress_callback: Optional[Callable[[int, int], None]] = None) -> bool:
        """
        Play a macro.

        Args:
            macro: Macro name (str), file path (str), or macro dict.
            speed: Playback speed multiplier.
                   1.0 = original speed, 2.0 = twice as fast, 0 = instant.
            repeat: Number of times to repeat the macro.
            stop_event: threading.Event — set it to stop playback.
            progress_callback: Called as callback(current_event, total_events).

        Returns:
            True if completed fully, False if stopped early.
        """
        if not _PYAUTOGUI_AVAILABLE:
            raise RuntimeError("pyautogui is required for macro playback.")

        # Load macro data
        if isinstance(macro, dict):
            data = macro
        else:
            data = MacroRecorder.load(macro)

        events: List[Dict[str, Any]] = data.get("events", [])
        if not events:
            logger.warning("Macro has no events")
            return True

        self._playing = True
        self._stop_event = stop_event or threading.Event()
        total = len(events)

        logger.info("Playing macro '%s' — %d events, speed=%.1fx, repeat=%d",
                    data.get("name", "?"), total, speed, repeat)

        try:
            for run in range(repeat):
                if self._stop_event.is_set():
                    break

                logger.info("Macro run %d/%d", run + 1, repeat)
                prev_time = 0.0

                for i, event in enumerate(events):
                    if self._stop_event.is_set():
                        logger.info("Macro stopped at event %d/%d", i, total)
                        return False

                    # Wait for the correct delay
                    event_time = event.get("time", 0.0)
                    delay = event_time - prev_time
                    if delay > 0 and speed > 0:
                        scaled_delay = delay / speed
                        # Sleep in small chunks so stop_event is checked
                        slept = 0.0
                        while slept < scaled_delay:
                            if self._stop_event.is_set():
                                return False
                            chunk = min(0.05, scaled_delay - slept)
                            time.sleep(chunk)
                            slept += chunk
                    prev_time = event_time

                    # Execute the event
                    self._execute_event(event)

                    if progress_callback:
                        try:
                            progress_callback(i + 1, total)
                        except Exception:
                            pass

            logger.info("Macro playback complete")
            return True

        except pyautogui.FailSafeException:
            logger.warning("Macro stopped: mouse moved to top-left corner (failsafe)")
            return False
        except Exception as e:
            logger.error("Macro playback error: %s", e)
            raise
        finally:
            self._playing = False

    def play_in_thread(self,
                       macro: Any,
                       speed: float = 1.0,
                       repeat: int = 1,
                       stop_event: Optional[threading.Event] = None,
                       progress_callback: Optional[Callable] = None,
                       done_callback: Optional[Callable[[bool], None]] = None
                       ) -> threading.Thread:
        """
        Play a macro in a background thread.

        Args:
            done_callback: Called with True/False when playback finishes.

        Returns:
            The running thread.
        """
        def _run():
            result = self.play(macro, speed=speed, repeat=repeat,
                               stop_event=stop_event,
                               progress_callback=progress_callback)
            if done_callback:
                done_callback(result)

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        return t

    # ------------------------------------------------------------------ #
    #  Event Execution                                                     #
    # ------------------------------------------------------------------ #

    def _execute_event(self, event: Dict[str, Any]) -> None:
        """Execute a single recorded event."""
        etype = event.get("type")

        try:
            if etype == "mouse_move":
                pyautogui.moveTo(event["x"], event["y"], duration=0)

            elif etype == "mouse_click":
                button = event.get("button", "left")
                pressed = event.get("pressed", True)
                x, y = event["x"], event["y"]
                if pressed:
                    pyautogui.mouseDown(x, y, button=button)
                else:
                    pyautogui.mouseUp(x, y, button=button)

            elif etype == "mouse_scroll":
                pyautogui.scroll(event.get("dy", 0), x=event["x"], y=event["y"])

            elif etype == "key_press":
                key = event.get("key", "")
                if len(key) == 1:
                    pyautogui.keyDown(key)
                else:
                    # Special key — map pynput names to pyautogui names
                    mapped = self._map_key(key)
                    if mapped:
                        pyautogui.keyDown(mapped)

            elif etype == "key_release":
                key = event.get("key", "")
                if len(key) == 1:
                    pyautogui.keyUp(key)
                else:
                    mapped = self._map_key(key)
                    if mapped:
                        pyautogui.keyUp(mapped)

        except Exception as e:
            logger.debug("Event execution error (%s): %s", etype, e)

    @staticmethod
    def _map_key(pynput_key: str) -> Optional[str]:
        """Map pynput key names to pyautogui key names."""
        mapping = {
            "enter": "enter", "return": "enter",
            "space": "space",
            "tab": "tab",
            "backspace": "backspace",
            "delete": "delete",
            "escape": "escape",
            "shift": "shift", "shift_l": "shiftleft", "shift_r": "shiftright",
            "ctrl": "ctrl", "ctrl_l": "ctrlleft", "ctrl_r": "ctrlright",
            "alt": "alt", "alt_l": "altleft", "alt_r": "altright",
            "cmd": "win", "cmd_l": "winleft", "cmd_r": "winright",
            "up": "up", "down": "down", "left": "left", "right": "right",
            "home": "home", "end": "end",
            "page_up": "pageup", "page_down": "pagedown",
            "f1": "f1", "f2": "f2", "f3": "f3", "f4": "f4",
            "f5": "f5", "f6": "f6", "f7": "f7", "f8": "f8",
            "f9": "f9", "f10": "f10", "f11": "f11", "f12": "f12",
            "caps_lock": "capslock",
            "num_lock": "numlock",
            "print_screen": "printscreen",
            "insert": "insert",
        }
        return mapping.get(pynput_key.lower())
