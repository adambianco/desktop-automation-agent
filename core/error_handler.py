"""
ErrorHandler — safe error recovery for desktop automation workflows.

Provides:
  - Retry decorator with exponential backoff
  - Safe action wrapper (catch, log, optionally screenshot on error)
  - Emergency abort (press Escape, move to safe position)
  - Error context manager for workflow steps
"""

import os
import time
import logging
import traceback
import functools
from typing import Callable, Optional, Type, Tuple, Any

logger = logging.getLogger(__name__)


class AutomationError(Exception):
    """Base exception for all desktop automation errors."""
    pass


class ElementNotFoundError(AutomationError):
    """Raised when a required UI element cannot be found."""
    pass


class WorkflowError(AutomationError):
    """Raised when a workflow step fails unrecoverably."""
    pass


class AbortWorkflow(AutomationError):
    """Raised to cleanly abort the current workflow."""
    pass


def retry(max_attempts: int = 3,
          delay: float = 1.0,
          backoff: float = 2.0,
          exceptions: Tuple[Type[Exception], ...] = (Exception,),
          on_retry: Optional[Callable] = None):
    """
    Decorator: retry a function on failure with exponential backoff.

    Args:
        max_attempts: Total number of attempts (including the first).
        delay: Initial delay between retries (seconds).
        backoff: Multiplier applied to delay after each failure.
        exceptions: Exception types that trigger a retry.
        on_retry: Optional callback(attempt, exception) called before each retry.

    Usage:
        @retry(max_attempts=3, delay=1.0)
        def click_save_button():
            ...
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            current_delay = delay
            last_exc = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt == max_attempts:
                        logger.error("All %d attempts failed for %s: %s",
                                     max_attempts, func.__name__, exc)
                        raise
                    logger.warning("Attempt %d/%d failed for %s: %s — retrying in %.1fs",
                                   attempt, max_attempts, func.__name__, exc, current_delay)
                    if on_retry:
                        on_retry(attempt, exc)
                    time.sleep(current_delay)
                    current_delay *= backoff
            raise last_exc
        return wrapper
    return decorator


class ErrorHandler:
    """
    Provides safe wrappers and recovery mechanisms for automation steps.

    Integrates with ScreenCapture to save debug screenshots on failure.
    """

    def __init__(self, screenshot_fn: Optional[Callable] = None,
                 debug_dir: str = "logs/errors"):
        """
        Args:
            screenshot_fn: Callable that returns a screenshot (np.ndarray).
                           Used to capture the screen state on error.
            debug_dir: Directory to save error screenshots.
        """
        self.screenshot_fn = screenshot_fn
        self.debug_dir = debug_dir
        os.makedirs(debug_dir, exist_ok=True)
        logger.info("ErrorHandler initialized (debug_dir=%s)", debug_dir)

    def safe_execute(self, action_fn: Callable,
                     description: str = "action",
                     fallback_fn: Optional[Callable] = None,
                     save_screenshot: bool = True) -> Tuple[bool, Any]:
        """
        Execute an action safely, catching all exceptions.

        Args:
            action_fn: The action to execute.
            description: Human-readable description for logging.
            fallback_fn: Optional fallback to run if action_fn fails.
            save_screenshot: Whether to save a debug screenshot on failure.

        Returns:
            (success: bool, result: Any) — result is None on failure.
        """
        try:
            result = action_fn()
            logger.debug("Action succeeded: %s", description)
            return True, result
        except AbortWorkflow:
            raise  # Always propagate abort signals
        except Exception as exc:
            logger.error("Action failed: %s — %s", description, exc)
            logger.debug("Traceback:\n%s", traceback.format_exc())

            if save_screenshot and self.screenshot_fn:
                self._save_error_screenshot(description)

            if fallback_fn:
                logger.info("Executing fallback for: %s", description)
                try:
                    result = fallback_fn()
                    return True, result
                except Exception as fb_exc:
                    logger.error("Fallback also failed: %s", fb_exc)

            return False, None

    def _save_error_screenshot(self, context: str) -> Optional[str]:
        """Save a screenshot for debugging purposes."""
        if not self.screenshot_fn:
            return None
        try:
            import cv2
            screen = self.screenshot_fn()
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            safe_context = "".join(c if c.isalnum() else "_" for c in context)[:40]
            path = os.path.join(self.debug_dir, f"error_{timestamp}_{safe_context}.png")
            cv2.imwrite(path, screen)
            logger.info("Error screenshot saved: %s", path)
            return path
        except Exception as e:
            logger.warning("Could not save error screenshot: %s", e)
            return None

    def emergency_abort(self, input_controller=None) -> None:
        """
        Perform an emergency abort:
          1. Press Escape to dismiss any open dialogs.
          2. Move mouse to a safe corner.
          3. Log the abort.
        """
        logger.critical("EMERGENCY ABORT triggered")
        if input_controller:
            try:
                input_controller.escape()
                time.sleep(0.2)
                input_controller.escape()
                time.sleep(0.2)
                input_controller.move_to(0, 0, duration=0.1)
            except Exception as e:
                logger.error("Emergency abort action failed: %s", e)
        raise AbortWorkflow("Emergency abort triggered")

    def assert_element_found(self, element, description: str = "element") -> None:
        """
        Assert that a UI element was found; raise ElementNotFoundError if not.
        """
        if element is None:
            raise ElementNotFoundError(
                f"Required element not found: {description}"
            )
        logger.debug("Element verified: %s → %s", description, element)

    def assert_condition(self, condition: bool, message: str) -> None:
        """Assert a boolean condition; raise WorkflowError if False."""
        if not condition:
            raise WorkflowError(f"Assertion failed: {message}")


class StepContext:
    """
    Context manager for a single workflow step.

    Logs entry/exit, measures duration, and handles errors gracefully.

    Usage:
        with StepContext("Fill Invoice Number", error_handler) as ctx:
            input_ctrl.type_text("INV-001")
    """

    def __init__(self, step_name: str, error_handler: ErrorHandler,
                 raise_on_error: bool = True):
        self.step_name = step_name
        self.error_handler = error_handler
        self.raise_on_error = raise_on_error
        self._start_time = None
        self.success = False
        self.error = None

    def __enter__(self):
        self._start_time = time.time()
        logger.info("▶ Step: %s", self.step_name)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed = time.time() - self._start_time
        if exc_type is None:
            self.success = True
            logger.info("✓ Step completed: %s (%.2fs)", self.step_name, elapsed)
            return False  # Don't suppress
        elif exc_type is AbortWorkflow:
            logger.critical("✗ Step aborted: %s", self.step_name)
            return False  # Propagate abort
        else:
            self.error = exc_val
            logger.error("✗ Step failed: %s — %s (%.2fs)",
                         self.step_name, exc_val, elapsed)
            self.error_handler._save_error_screenshot(self.step_name)
            if self.raise_on_error:
                return False  # Propagate exception
            return True  # Suppress exception
