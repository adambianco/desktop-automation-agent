"""
ScreenCapture — provides fast, reliable screenshot functionality.

Uses `mss` for high-performance screen capture (faster than pyautogui.screenshot).
Supports full-screen, region, and multi-monitor capture.
"""

import os
import time
import logging
from typing import Optional, Tuple

import mss
import mss.tools
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


class ScreenCapture:
    """
    Captures screenshots as NumPy arrays (BGR format for OpenCV compatibility)
    or as PIL Images.

    Usage:
        sc = ScreenCapture()
        frame = sc.capture()          # Full screen as numpy array
        region = sc.capture_region(x, y, w, h)
        sc.save_screenshot("debug.png")
    """

    def __init__(self, monitor_index: int = 1):
        """
        Args:
            monitor_index: 1-based monitor index (1 = primary).
                           0 = combined virtual screen of all monitors.
        """
        self.monitor_index = monitor_index
        self._sct = mss.mss()
        monitors = self._sct.monitors
        if monitor_index >= len(monitors):
            logger.warning("Monitor %d not found; falling back to monitor 1", monitor_index)
            self.monitor_index = 1
        self.monitor = self._sct.monitors[self.monitor_index]
        logger.info("ScreenCapture initialized: monitor %d → %s", self.monitor_index, self.monitor)

    def capture(self) -> np.ndarray:
        """
        Capture the full screen and return as a BGR NumPy array
        (compatible with OpenCV).
        """
        raw = self._sct.grab(self.monitor)
        # mss returns BGRA; drop alpha channel for OpenCV
        frame = np.array(raw)[:, :, :3]
        logger.debug("Screen captured: %dx%d", frame.shape[1], frame.shape[0])
        return frame

    def capture_region(self, x: int, y: int, width: int, height: int) -> np.ndarray:
        """
        Capture a specific rectangular region of the screen.

        Args:
            x, y: Top-left corner of the region (absolute screen coordinates).
            width, height: Dimensions of the region.

        Returns:
            BGR NumPy array of the captured region.
        """
        region = {"top": y, "left": x, "width": width, "height": height}
        raw = self._sct.grab(region)
        frame = np.array(raw)[:, :, :3]
        logger.debug("Region captured: (%d,%d) %dx%d", x, y, width, height)
        return frame

    def capture_pil(self) -> Image.Image:
        """Capture the full screen and return as a PIL Image (RGB)."""
        frame_bgr = self.capture()
        frame_rgb = frame_bgr[:, :, ::-1]  # BGR → RGB
        return Image.fromarray(frame_rgb)

    def save_screenshot(self, path: str, region: Optional[Tuple] = None) -> str:
        """
        Save a screenshot to disk.

        Args:
            path: File path to save the image.
            region: Optional (x, y, width, height) tuple for a region capture.

        Returns:
            Absolute path of the saved file.
        """
        if region:
            frame = self.capture_region(*region)
        else:
            frame = self.capture()

        img = Image.fromarray(frame[:, :, ::-1])  # BGR → RGB
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        img.save(path)
        logger.info("Screenshot saved: %s", path)
        return os.path.abspath(path)

    def get_screen_size(self) -> Tuple[int, int]:
        """Return (width, height) of the monitored screen."""
        return self.monitor["width"], self.monitor["height"]

    def close(self) -> None:
        """Release the mss context."""
        self._sct.close()
        logger.debug("ScreenCapture closed")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
