"""
WorkflowBase — abstract base class for all workflow plugins.

Every workflow plugin must inherit from WorkflowBase and implement:
  - name: str property (unique workflow identifier)
  - description: str property (human-readable description)
  - required_config: list of required config keys
  - setup(): one-time initialization before processing rows
  - process_row(row, context): process a single data row
  - teardown(): cleanup after all rows are processed

Optionally override:
  - validate_config(): custom config validation
  - on_row_error(row, error, context): custom error handling per row
  - on_complete(results, context): called after all rows succeed
"""

import abc
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class WorkflowResult:
    """Holds the result of processing a single row."""

    def __init__(self, row_index: int, success: bool,
                 data: Optional[Dict] = None,
                 error: Optional[str] = None,
                 duration: float = 0.0):
        self.row_index = row_index
        self.success = success
        self.data = data or {}
        self.error = error
        self.duration = duration

    def __repr__(self) -> str:
        status = "OK" if self.success else f"FAIL: {self.error}"
        return f"WorkflowResult(row={self.row_index}, {status}, {self.duration:.2f}s)"


class WorkflowSummary:
    """Aggregated results for a complete workflow run."""

    def __init__(self, workflow_name: str):
        self.workflow_name = workflow_name
        self.results: List[WorkflowResult] = []
        self.start_time: float = time.time()
        self.end_time: Optional[float] = None

    def add(self, result: WorkflowResult) -> None:
        self.results.append(result)

    def finish(self) -> None:
        self.end_time = time.time()

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def succeeded(self) -> int:
        return sum(1 for r in self.results if r.success)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.success)

    @property
    def duration(self) -> float:
        if self.end_time:
            return self.end_time - self.start_time
        return time.time() - self.start_time

    @property
    def success_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.succeeded / self.total

    def failed_rows(self) -> List[WorkflowResult]:
        return [r for r in self.results if not r.success]

    def __repr__(self) -> str:
        return (f"WorkflowSummary({self.workflow_name!r}: "
                f"{self.succeeded}/{self.total} OK, "
                f"{self.duration:.1f}s)")


class WorkflowBase(abc.ABC):
    """
    Abstract base class for all workflow plugins.

    Subclasses define the automation logic for a specific workflow.
    The WorkflowEngine calls setup(), then process_row() for each data row,
    then teardown().
    """

    def __init__(self):
        self._logger = logging.getLogger(
            f"workflow.{self.__class__.__name__}"
        )

    # ------------------------------------------------------------------ #
    #  Abstract Properties (must be defined by subclass)                  #
    # ------------------------------------------------------------------ #

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Unique machine-readable workflow identifier (e.g. 'erp_data_entry')."""
        ...

    @property
    @abc.abstractmethod
    def description(self) -> str:
        """Human-readable description of what this workflow does."""
        ...

    @property
    def version(self) -> str:
        """Workflow version string."""
        return "1.0.0"

    @property
    def required_config(self) -> List[str]:
        """List of required configuration keys."""
        return []

    @property
    def required_columns(self) -> List[str]:
        """List of required spreadsheet columns."""
        return []

    # ------------------------------------------------------------------ #
    #  Lifecycle Methods (override as needed)                             #
    # ------------------------------------------------------------------ #

    def validate_config(self, config: Dict[str, Any]) -> List[str]:
        """
        Validate the workflow configuration.

        Returns:
            List of validation error messages (empty if valid).
        """
        errors = []
        for key in self.required_config:
            if key not in config:
                errors.append(f"Missing required config key: '{key}'")
        return errors

    def setup(self, context: Any) -> None:
        """
        One-time setup before processing begins.

        Override to open applications, navigate to the correct screen,
        log in, etc.
        """
        self._logger.info("Workflow setup: %s v%s", self.name, self.version)

    @abc.abstractmethod
    def process_row(self, row: Dict[str, Any], context: Any) -> WorkflowResult:
        """
        Process a single data row.

        Args:
            row: A mapped data dictionary from the DataMapper.
            context: The AgentContext with all platform components.

        Returns:
            WorkflowResult indicating success or failure.
        """
        ...

    def teardown(self, context: Any, summary: WorkflowSummary) -> None:
        """
        Cleanup after all rows are processed.

        Override to close applications, save reports, log out, etc.
        """
        self._logger.info("Workflow teardown: %s — %s", self.name, summary)

    def on_row_error(self, row: Dict[str, Any], error: Exception,
                     context: Any) -> bool:
        """
        Called when process_row() raises an exception.

        Args:
            row: The row that caused the error.
            error: The exception that was raised.
            context: The AgentContext.

        Returns:
            True to continue with the next row, False to abort the workflow.
        """
        self._logger.error("Row %s error: %s", row.get("_row_index", "?"), error)
        return True  # Continue by default

    def on_complete(self, summary: WorkflowSummary, context: Any) -> None:
        """Called after all rows are processed and teardown is complete."""
        self._logger.info("Workflow complete: %s", summary)

    # ------------------------------------------------------------------ #
    #  Utility Methods                                                     #
    # ------------------------------------------------------------------ #

    def log_step(self, message: str, *args) -> None:
        """Log a workflow step at INFO level."""
        self._logger.info(message, *args)

    def log_debug(self, message: str, *args) -> None:
        """Log a debug message."""
        self._logger.debug(message, *args)

    def log_warning(self, message: str, *args) -> None:
        """Log a warning."""
        self._logger.warning(message, *args)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r}, v{self.version})"
