"""
WaitHandler — robust waiting and polling for UI elements.

Provides:
  - wait_for_element: poll until a UI element appears (template or text)
  - wait_for_element_to_disappear: poll until an element is gone
  - wait_for_color: poll until a pixel reaches an expected color
  - wait_for_stable_screen: wait until the screen stops changing
  - wait_for_window_title: poll for a window title (via subprocess)
  - Configurable timeout, poll interval, and retry logic
"""

import time
import logging
import subprocess
from typing import Optional, Callable, Any, Tuple

import numpy as np

logger = logging.getLogger(__name__)


class TimeoutError(Exception):
    """Raised when a wait operation exceeds its timeout."""
    pass


class WaitHandler:
    """
    Provides polling-based wait primitives for reliable UI synchronization.

    All wait methods accept a `timeout` (seconds) and `poll_interval` (seconds).
    On timeout, they either raise TimeoutError or return None/False depending
    on the method, allowing the caller to decide how to handle the failure.
    """

    def __init__(self, default_timeout: float = 30.0,
                 default_poll_interval: float = 0.5):
        self.default_timeout = default_timeout
        self.default_poll_interval = default_poll_interval
        logger.info("WaitHandler initialized (timeout=%.1fs, poll=%.2fs)",
                    default_timeout, default_poll_interval)

    # ------------------------------------------------------------------ #
    #  Core Polling Primitive                                              #
    # ------------------------------------------------------------------ #

    def poll_until(self, condition_fn: Callable[[], Any],
                   timeout: float = None,
                   poll_interval: float = None,
                   description: str = "condition",
                   raise_on_timeout: bool = True) -> Any:
        """
        Poll condition_fn() until it returns a truthy value or timeout.

        Args:
            condition_fn: Callable that returns a truthy result when ready.
            timeout: Maximum wait time in seconds.
            poll_interval: How often to check (seconds).
            description: Human-readable description for logging.
            raise_on_timeout: If True, raise TimeoutError on timeout.

        Returns:
            The truthy result of condition_fn(), or None on timeout.
        """
        timeout = timeout if timeout is not None else self.default_timeout
        poll_interval = poll_interval if poll_interval is not None else self.default_poll_interval
        deadline = time.time() + timeout
        attempt = 0

        logger.debug("Waiting for: %s (timeout=%.1fs)", description, timeout)

        while time.time() < deadline:
            attempt += 1
            result = condition_fn()
            if result:
                elapsed = time.time() - (deadline - timeout)
                logger.debug("Condition met: %s (attempt=%d, elapsed=%.2fs)",
                             description, attempt, elapsed)
                return result
            time.sleep(poll_interval)

        logger.warning("Timeout waiting for: %s (%.1fs elapsed)", description, timeout)
        if raise_on_timeout:
            raise TimeoutError(f"Timeout ({timeout}s) waiting for: {description}")
        return None

    # ------------------------------------------------------------------ #
    #  Element Waiting                                                     #
    # ------------------------------------------------------------------ #

    def wait_for_element(self, capture_fn: Callable[[], np.ndarray],
                         detect_fn: Callable[[np.ndarray], Any],
                         timeout: float = None,
                         poll_interval: float = None,
                         description: str = "UI element",
                         raise_on_timeout: bool = True) -> Any:
        """
        Wait for a UI element to appear on screen.

        Args:
            capture_fn: Callable that returns a fresh screenshot (np.ndarray).
            detect_fn: Callable(screen) → UIElement or None.
            timeout: Maximum wait time.
            poll_interval: How often to capture and check.
            description: Human-readable description for logging.
            raise_on_timeout: Whether to raise on timeout.

        Returns:
            The UIElement when found, or None on timeout (if not raising).
        """
        def _check():
            screen = capture_fn()
            return detect_fn(screen)

        return self.poll_until(
            _check,
            timeout=timeout,
            poll_interval=poll_interval,
            description=description,
            raise_on_timeout=raise_on_timeout
        )

    def wait_for_element_to_disappear(self, capture_fn: Callable[[], np.ndarray],
                                      detect_fn: Callable[[np.ndarray], Any],
                                      timeout: float = None,
                                      poll_interval: float = None,
                                      description: str = "UI element disappear"
                                      ) -> bool:
        """
        Wait until a UI element is no longer visible on screen.

        Returns:
            True when the element disappears, raises TimeoutError otherwise.
        """
        def _check():
            screen = capture_fn()
            return not detect_fn(screen)

        result = self.poll_until(
            _check,
            timeout=timeout,
            poll_interval=poll_interval,
            description=f"disappear: {description}",
            raise_on_timeout=True
        )
        return bool(result)

    # ------------------------------------------------------------------ #
    #  Screen Stability                                                    #
    # ------------------------------------------------------------------ #

    def wait_for_stable_screen(self, capture_fn: Callable[[], np.ndarray],
                                stable_duration: float = 1.0,
                                change_threshold: float = 0.01,
                                timeout: float = None,
                                poll_interval: float = 0.3) -> np.ndarray:
        """
        Wait until the screen stops changing (page load, animation complete, etc.).

        Args:
            capture_fn: Returns a fresh screenshot.
            stable_duration: How long the screen must remain stable (seconds).
            change_threshold: Fraction of pixels that must differ to count as change.
            timeout: Maximum total wait time.
            poll_interval: How often to check.

        Returns:
            The stable screenshot as a NumPy array.
        """
        timeout = timeout if timeout is not None else self.default_timeout
        deadline = time.time() + timeout
        stable_since = None
        prev_frame = None

        logger.debug("Waiting for stable screen (stable_duration=%.1fs)", stable_duration)

        while time.time() < deadline:
            frame = capture_fn()

            if prev_frame is not None:
                diff = np.mean(np.abs(frame.astype(float) - prev_frame.astype(float))) / 255.0
                if diff < change_threshold:
                    if stable_since is None:
                        stable_since = time.time()
                    elif time.time() - stable_since >= stable_duration:
                        logger.debug("Screen stable after %.2fs", time.time() - stable_since)
                        return frame
                else:
                    stable_since = None
            else:
                stable_since = None

            prev_frame = frame
            time.sleep(poll_interval)

        raise TimeoutError(f"Screen did not stabilize within {timeout}s")

    # ------------------------------------------------------------------ #
    #  Color Waiting                                                       #
    # ------------------------------------------------------------------ #

    def wait_for_pixel_color(self, capture_fn: Callable[[], np.ndarray],
                             x: int, y: int,
                             expected_rgb: Tuple[int, int, int],
                             tolerance: int = 15,
                             timeout: float = None,
                             poll_interval: float = 0.3,
                             description: str = "pixel color") -> bool:
        """
        Wait until a specific pixel reaches an expected color.

        Useful for detecting loading spinners, status indicators, etc.
        """
        def _check():
            screen = capture_fn()
            bgr = screen[y, x]
            r, g, b = int(bgr[2]), int(bgr[1]), int(bgr[0])
            er, eg, eb = expected_rgb
            return (abs(r - er) <= tolerance and
                    abs(g - eg) <= tolerance and
                    abs(b - eb) <= tolerance)

        result = self.poll_until(
            _check,
            timeout=timeout,
            poll_interval=poll_interval,
            description=f"pixel ({x},{y}) color {expected_rgb}",
            raise_on_timeout=True
        )
        return bool(result)

    # ------------------------------------------------------------------ #
    #  Simple Delays                                                       #
    # ------------------------------------------------------------------ #

    def sleep(self, seconds: float) -> None:
        """Simple sleep — use for fixed delays when polling is unnecessary."""
        logger.debug("Sleep %.2fs", seconds)
        time.sleep(seconds)

    def short_pause(self) -> None:
        """A brief 0.3s pause for UI to catch up after an action."""
        time.sleep(0.3)

    def medium_pause(self) -> None:
        """A 1.0s pause for slower UI transitions."""
        time.sleep(1.0)

    def long_pause(self) -> None:
        """A 3.0s pause for heavy operations (file load, network request)."""
        time.sleep(3.0)
