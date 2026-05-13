"""
WorkflowEngine — orchestrates workflow execution end-to-end.

Responsibilities:
  - Load and validate workflow plugins
  - Load and validate spreadsheet data
  - Map data rows to workflow context
  - Run setup → process_row (for each row) → teardown
  - Track progress, handle errors, and produce a summary report
  - Support resume from a specific row (crash recovery)
  - Emit progress events for the CLI/UI
"""

import os
import sys
import time
import json
import logging
from typing import Optional, Dict, Any, List, Callable, Type

logger = logging.getLogger(__name__)


class WorkflowEngine:
    """
    Orchestrates the execution of a workflow against a dataset.

    Usage:
        engine = WorkflowEngine(context)
        engine.register_workflow(ERPDataEntryWorkflow)

        summary = engine.run(
            workflow_name="erp_data_entry",
            data_file="invoices.xlsx",
            config={"app_path": "/usr/bin/erp"},
            start_row=0
        )
    """

    def __init__(self, context, progress_callback: Optional[Callable] = None):
        """
        Args:
            context: AgentContext with all platform components.
            progress_callback: Optional callable(current, total, result) for progress updates.
        """
        self.context = context
        self.progress_callback = progress_callback
        self._workflow_registry: Dict[str, Type] = {}
        logger.info("WorkflowEngine initialized")

    # ------------------------------------------------------------------ #
    #  Workflow Registration                                               #
    # ------------------------------------------------------------------ #

    def register_workflow(self, workflow_class) -> None:
        """
        Register a workflow plugin class.

        Args:
            workflow_class: A class that inherits from WorkflowBase.
        """
        instance = workflow_class()
        name = instance.name
        self._workflow_registry[name] = workflow_class
        logger.info("Workflow registered: %s v%s", name, instance.version)

    def register_all_from_directory(self, workflows_dir: str = "workflows") -> int:
        """
        Auto-discover and register all workflow plugins in a directory.

        Each .py file in the directory that contains a WorkflowBase subclass
        will be imported and registered automatically.

        Returns:
            Number of workflows registered.
        """
        import importlib.util

        count = 0
        if not os.path.isdir(workflows_dir):
            logger.warning("Workflows directory not found: %s", workflows_dir)
            return 0

        for filename in os.listdir(workflows_dir):
            if not filename.endswith(".py") or filename.startswith("_"):
                continue
            module_path = os.path.join(workflows_dir, filename)
            module_name = filename[:-3]
            try:
                spec = importlib.util.spec_from_file_location(module_name, module_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                # Find WorkflowBase subclasses in the module
                from engine.workflow_base import WorkflowBase
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (isinstance(attr, type) and
                            issubclass(attr, WorkflowBase) and
                            attr is not WorkflowBase):
                        self.register_workflow(attr)
                        count += 1
            except Exception as e:
                logger.error("Failed to load workflow from %s: %s", filename, e)

        logger.info("Auto-registered %d workflows from %s", count, workflows_dir)
        return count

    def list_workflows(self) -> List[Dict[str, str]]:
        """Return a list of registered workflow metadata."""
        result = []
        for name, cls in self._workflow_registry.items():
            instance = cls()
            result.append({
                "name": instance.name,
                "description": instance.description,
                "version": instance.version,
                "required_config": instance.required_config,
                "required_columns": instance.required_columns,
            })
        return result

    # ------------------------------------------------------------------ #
    #  Main Execution                                                      #
    # ------------------------------------------------------------------ #

    def run(self,
            workflow_name: str,
            data_file: str,
            config: Optional[Dict[str, Any]] = None,
            start_row: int = 0,
            end_row: Optional[int] = None,
            sheet: Any = 0,
            column_map: Optional[Dict[str, str]] = None,
            dry_run: bool = False,
            stop_event=None) -> "WorkflowSummary":
        """
        Execute a workflow against a data file.

        Args:
            workflow_name: Name of the registered workflow to run.
            data_file: Path to the Excel or CSV data file.
            config: Workflow configuration dictionary.
            start_row: 0-based row index to start from (for resume).
            end_row: 0-based row index to stop at (exclusive).
            sheet: Sheet name or index (Excel only).
            column_map: Optional column renaming map.
            dry_run: If True, load and validate data but don't execute.

        Returns:
            WorkflowSummary with results for all processed rows.
        """
        from engine.workflow_base import WorkflowBase, WorkflowSummary, WorkflowResult
        from data.spreadsheet_reader import SpreadsheetReader
        from data.data_mapper import DataMapper, FieldMapping

        config = config or {}

        # --- Resolve workflow ---
        if workflow_name not in self._workflow_registry:
            available = list(self._workflow_registry.keys())
            raise ValueError(
                f"Workflow '{workflow_name}' not registered. "
                f"Available: {available}"
            )
        workflow: WorkflowBase = self._workflow_registry[workflow_name]()
        logger.info("Running workflow: %s v%s", workflow.name, workflow.version)

        # --- Validate config ---
        config_errors = workflow.validate_config(config)
        if config_errors:
            raise ValueError(
                f"Workflow config errors:\n" +
                "\n".join(f"  - {e}" for e in config_errors)
            )

        # --- Update context config ---
        self.context.config.update(config)

        # --- Load data ---
        reader = SpreadsheetReader(data_file)
        reader.load(sheet=sheet, column_map=column_map)

        # --- Validate required columns ---
        missing_cols = reader.validate_columns(workflow.required_columns)
        if missing_cols:
            raise ValueError(
                f"Missing required columns for workflow '{workflow_name}': {missing_cols}"
            )

        total_rows = reader.row_count
        logger.info("Data loaded: %d rows from %s", total_rows, data_file)

        if dry_run:
            logger.info("DRY RUN: validation complete, skipping execution")
            summary = WorkflowSummary(workflow_name)
            summary.finish()
            return summary

        # --- Execute workflow ---
        summary = WorkflowSummary(workflow_name)
        progress_file = self._get_progress_file(workflow_name, data_file)

        # Setup
        try:
            workflow.setup(self.context)
        except Exception as e:
            logger.error("Workflow setup failed: %s", e)
            raise

        # Process rows
        for row in reader.iter_rows(start_row=start_row, end_row=end_row):
            # Check stop signal before each row
            if stop_event is not None and stop_event.is_set():
                logger.info("Workflow stopped by user at row %d", row.get('_row_index', 0) + 1)
                break

            row_idx = row.get("_row_index", 0)
            row_start = time.time()

            logger.info("Processing row %d / %d", row_idx + 1, total_rows)

            try:
                result = workflow.process_row(row, self.context)
                result.row_index = row_idx
                result.duration = time.time() - row_start
            except Exception as e:
                logger.error("Row %d raised exception: %s", row_idx, e)
                result = WorkflowResult(
                    row_index=row_idx,
                    success=False,
                    error=str(e),
                    duration=time.time() - row_start
                )
                should_continue = workflow.on_row_error(row, e, self.context)
                if not should_continue:
                    logger.warning("Workflow aborted by on_row_error at row %d", row_idx)
                    summary.add(result)
                    break

            summary.add(result)
            self._save_progress(progress_file, row_idx + 1, summary)

            if self.progress_callback:
                self.progress_callback(row_idx + 1, total_rows, result)

        # Teardown
        try:
            workflow.teardown(self.context, summary)
        except Exception as e:
            logger.error("Workflow teardown error: %s", e)

        summary.finish()
        workflow.on_complete(summary, self.context)
        self._cleanup_progress(progress_file)

        logger.info("Workflow complete: %s", summary)
        return summary

    # ------------------------------------------------------------------ #
    #  Progress / Resume Support                                           #
    # ------------------------------------------------------------------ #

    def _get_progress_file(self, workflow_name: str, data_file: str) -> str:
        """Return the path to the progress tracking file."""
        safe_name = "".join(c if c.isalnum() else "_" for c in workflow_name)
        safe_file = "".join(c if c.isalnum() else "_" for c in os.path.basename(data_file))
        return os.path.join("logs", f"progress_{safe_name}_{safe_file}.json")

    def _save_progress(self, progress_file: str, last_row: int,
                       summary: "WorkflowSummary") -> None:
        """Save progress to disk for crash recovery."""
        os.makedirs(os.path.dirname(progress_file), exist_ok=True)
        data = {
            "last_completed_row": last_row,
            "succeeded": summary.succeeded,
            "failed": summary.failed,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        with open(progress_file, "w") as f:
            json.dump(data, f, indent=2)

    def _cleanup_progress(self, progress_file: str) -> None:
        """Remove the progress file after successful completion."""
        if os.path.exists(progress_file):
            os.remove(progress_file)

    def get_resume_row(self, workflow_name: str, data_file: str) -> int:
        """
        Return the row to resume from after a crash.

        Returns:
            The last completed row index + 1, or 0 if no progress file exists.
        """
        progress_file = self._get_progress_file(workflow_name, data_file)
        if os.path.exists(progress_file):
            with open(progress_file) as f:
                data = json.load(f)
            resume_row = data.get("last_completed_row", 0)
            logger.info("Resuming from row %d (progress file: %s)",
                        resume_row, progress_file)
            return resume_row
        return 0
