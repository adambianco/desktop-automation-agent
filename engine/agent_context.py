"""
AgentContext — the shared runtime context for all workflows.

Holds references to all core platform components (input controller,
screen capture, vision, wait handler, error handler, clipboard manager)
and provides a single object that workflows receive to do their work.

This eliminates the need for workflows to instantiate their own components
and ensures consistent configuration across the entire platform.
"""

import os
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class AgentContext:
    """
    Central context object passed to every workflow and step.

    Attributes:
        input:      InputController — mouse and keyboard control
        screen:     ScreenCapture — screenshot capture
        vision:     Vision — UI element detection
        wait:       WaitHandler — polling and synchronization
        errors:     ErrorHandler — safe error recovery
        clipboard:  ClipboardManager — clipboard operations
        config:     Dict — workflow-specific configuration
        state:      Dict — mutable runtime state (shared across steps)
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None,
                 display: str = ":99",
                 template_dir: str = "templates",
                 log_dir: str = "logs",
                 debug_screenshots: bool = True):
        """
        Initialize all platform components.

        Args:
            config: Workflow configuration dictionary.
            display: X display to use (headless: ":99", real: ":0").
            template_dir: Directory containing UI template images.
            log_dir: Directory for logs and error screenshots.
            debug_screenshots: Whether to save screenshots on errors.
        """
        os.environ["DISPLAY"] = display
        self.config = config or {}
        self.state: Dict[str, Any] = {}
        self._debug_screenshots = debug_screenshots

        # Lazy imports to avoid circular dependencies
        from core.input_controller import InputController
        from core.screen_capture import ScreenCapture
        from core.vision import Vision
        from core.wait_handler import WaitHandler
        from core.error_handler import ErrorHandler
        from data.clipboard_manager import ClipboardManager

        self.input = InputController(
            typing_interval=self.config.get("typing_interval", 0.03),
            move_duration=self.config.get("move_duration", 0.2)
        )
        self.screen = ScreenCapture(
            monitor_index=self.config.get("monitor_index", 1)
        )
        self.vision = Vision(
            template_dir=template_dir,
            default_threshold=self.config.get("vision_threshold", 0.80)
        )
        self.wait = WaitHandler(
            default_timeout=self.config.get("default_timeout", 30.0),
            default_poll_interval=self.config.get("poll_interval", 0.5)
        )
        self.errors = ErrorHandler(
            screenshot_fn=self.screen.capture if debug_screenshots else None,
            debug_dir=os.path.join(log_dir, "errors")
        )
        self.clipboard = ClipboardManager(
            history_size=self.config.get("clipboard_history", 20)
        )

        logger.info("AgentContext initialized (display=%s, template_dir=%s)",
                    display, template_dir)

    # ------------------------------------------------------------------ #
    #  Convenience Methods                                                 #
    # ------------------------------------------------------------------ #

    def capture(self):
        """Capture a fresh screenshot (returns BGR NumPy array)."""
        return self.screen.capture()

    def find(self, template_path: str, label: str = "",
             threshold: float = None, region=None):
        """Find a UI element by template image on the current screen."""
        screen = self.capture()
        return self.vision.find_template(screen, template_path, label=label,
                                         threshold=threshold, region=region)

    def find_text(self, text: str, label: str = "", region=None):
        """Find a UI element by text (OCR) on the current screen."""
        screen = self.capture()
        return self.vision.find_text(screen, text, label=label, region=region)

    def wait_for(self, template_path: str, label: str = "",
                 timeout: float = None, threshold: float = None):
        """Wait for a template to appear on screen."""
        return self.wait.wait_for_element(
            capture_fn=self.capture,
            detect_fn=lambda s: self.vision.find_template(
                s, template_path, label=label, threshold=threshold),
            timeout=timeout,
            description=label or template_path
        )

    def wait_for_text(self, text: str, timeout: float = None):
        """Wait for text to appear on screen (OCR)."""
        return self.wait.wait_for_element(
            capture_fn=self.capture,
            detect_fn=lambda s: self.vision.find_text(s, text),
            timeout=timeout,
            description=f"text: {text!r}"
        )

    def click_element(self, element, offset_x: int = 0, offset_y: int = 0) -> None:
        """Click the center of a UIElement."""
        cx, cy = element.center
        self.input.click(cx + offset_x, cy + offset_y)

    def find_and_click(self, template_path: str, label: str = "",
                       timeout: float = None) -> bool:
        """Wait for a template to appear, then click it."""
        element = self.wait_for(template_path, label=label, timeout=timeout)
        if element:
            self.click_element(element)
            return True
        return False

    def type_into_field(self, value: Any, clear_first: bool = True) -> None:
        """Clear the current field and type a value using clipboard paste."""
        if clear_first:
            self.input.clear_field()
            self.input.sleep(0.05)
        with self.clipboard.preserve():
            self.clipboard.copy(str(value))
            self.input.paste()

    def set_state(self, key: str, value: Any) -> None:
        """Set a value in the shared runtime state."""
        self.state[key] = value

    def get_state(self, key: str, default: Any = None) -> Any:
        """Get a value from the shared runtime state."""
        return self.state.get(key, default)

    def close(self) -> None:
        """Release all resources."""
        self.screen.close()
        logger.info("AgentContext closed")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
