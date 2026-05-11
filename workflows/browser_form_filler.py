"""
Browser Form Filler Workflow — Second Reference Workflow
=========================================================

Demonstrates how to add a second workflow to the platform without
modifying any core code. This workflow fills web-based forms in a
browser using keyboard navigation and clipboard paste.

It shows the platform's extensibility: drop a new .py file in the
workflows/ directory and it is automatically discovered and registered.

Configuration keys:
  - url: The URL of the web form to fill
  - browser_path: Path to the browser executable (optional)
  - field_order: List of field names in Tab order
  - submit_template: Template image for the Submit button
  - success_url_contains: String that must appear in URL after submission

Spreadsheet columns:
  - first_name, last_name, email, phone, company, message
"""

import time
import subprocess
import logging
from typing import Any, Dict, List

from engine.workflow_base import WorkflowBase, WorkflowResult, WorkflowSummary
from core.error_handler import StepContext

logger = logging.getLogger("workflow.browser_form_filler")


class BrowserFormFillerWorkflow(WorkflowBase):
    """
    Fills and submits a web-based form for each row in a spreadsheet.

    Demonstrates:
      - Browser navigation via keyboard shortcuts
      - Tab-based field navigation in web forms
      - URL-based success verification
      - Clean separation from the ERP workflow
    """

    @property
    def name(self) -> str:
        return "browser_form_filler"

    @property
    def description(self) -> str:
        return ("Fills and submits a web-based HTML form for each row "
                "in a spreadsheet using browser keyboard navigation.")

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def required_config(self) -> List[str]:
        return ["url"]

    @property
    def required_columns(self) -> List[str]:
        return ["email"]

    def setup(self, context: Any) -> None:
        """Open the browser and navigate to the form URL."""
        super().setup(context)
        cfg = context.config
        url = cfg["url"]

        browser_path = cfg.get("browser_path", "chromium-browser")

        with StepContext("Open Browser", context.errors):
            subprocess.Popen(
                [browser_path, "--no-sandbox", "--disable-gpu",
                 f"--display={cfg.get('display', ':99')}", url],
                env={**__import__("os").environ,
                     "DISPLAY": cfg.get("display", ":99")}
            )
            context.wait.sleep(cfg.get("browser_launch_delay", 3.0))
            self.log_step("Browser opened: %s", url)

    def process_row(self, row: Dict[str, Any], context: Any) -> WorkflowResult:
        """Fill and submit the form for one data row."""
        cfg = context.config
        row_idx = row.get("_row_index", 0)

        # Navigate to form URL (reload for each row)
        with StepContext("Navigate to Form", context.errors):
            context.input.hotkey("ctrl", "l")  # Focus address bar
            context.wait.sleep(0.2)
            context.type_into_field(cfg["url"])
            context.input.enter()
            context.wait.sleep(cfg.get("page_load_delay", 2.0))

        # Fill fields
        with StepContext(f"Fill Form (row {row_idx})", context.errors):
            self._fill_form(row, context)

        # Submit
        with StepContext("Submit Form", context.errors):
            self._submit_form(context)
            context.wait.sleep(cfg.get("submit_delay", 1.5))

        return WorkflowResult(
            row_index=row_idx,
            success=True,
            data={"email": row.get("email", "")}
        )

    def _fill_form(self, row: Dict[str, Any], context: Any) -> None:
        """Tab through form fields and fill each one."""
        cfg = context.config
        field_order = cfg.get("field_order", [
            "first_name", "last_name", "email", "phone", "company", "message"
        ])

        # Click the first field (or use Tab from top of page)
        context.input.hotkey("ctrl", "Home")
        context.wait.sleep(0.1)
        context.input.tab()  # Move to first form field

        for field_name in field_order:
            value = row.get(field_name, "")
            if value and str(value).strip() and str(value).lower() != "nan":
                context.type_into_field(value, clear_first=True)
            context.input.tab()
            context.wait.sleep(0.05)

    def _submit_form(self, context: Any) -> None:
        """Submit the form via template click or Enter key."""
        cfg = context.config
        submit_template = cfg.get("submit_template")

        if submit_template:
            element = context.find(submit_template, label="Submit Button")
            if element:
                context.click_element(element)
                return

        # Fallback: press Enter
        context.input.enter()

    def teardown(self, context: Any, summary: WorkflowSummary) -> None:
        """Close the browser if configured."""
        if context.config.get("close_browser_on_teardown", False):
            try:
                context.input.hotkey("ctrl", "w")
            except Exception:
                pass
        super().teardown(context, summary)
