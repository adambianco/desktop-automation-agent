"""
ERP Data Entry Workflow — Reference Implementation
===================================================

Automates the entry of records from a spreadsheet into a generic ERP
application. This workflow demonstrates the full capabilities of the
Desktop Automation Agent platform.

Supported ERP interaction modes:
  1. Template-based: locate buttons/fields by screenshot templates
  2. Tab-navigation: navigate fields using Tab key (most ERP apps)
  3. OCR-based: find fields by their label text on screen

Configuration keys:
  - app_path (optional): Path to the ERP executable to launch
  - app_window_title: Window title to identify the ERP window
  - entry_mode: "template" | "tab" | "ocr" (default: "tab")
  - new_record_template: Template image for the "New Record" button
  - save_template: Template image for the "Save" button
  - field_order: List of field names in Tab order
  - inter_row_delay: Seconds to wait between rows (default: 0.5)
  - max_retries: Max retries per row on failure (default: 2)

Spreadsheet columns (configurable via column_map):
  - invoice_number
  - vendor_name
  - invoice_date
  - amount
  - description
  - cost_center (optional)
  - purchase_order (optional)

Usage:
    from workflows.erp_data_entry import ERPDataEntryWorkflow
    engine.register_workflow(ERPDataEntryWorkflow)
    engine.run("erp_data_entry", "invoices.xlsx", config={...})
"""

import time
import logging
import subprocess
from typing import Any, Dict, List, Optional

from engine.workflow_base import WorkflowBase, WorkflowResult, WorkflowSummary
from core.error_handler import StepContext, ElementNotFoundError, retry

logger = logging.getLogger("workflow.erp_data_entry")


class ERPDataEntryWorkflow(WorkflowBase):
    """
    Automates data entry into a generic ERP application.

    This is the reference implementation demonstrating:
      - Application launch and window focus
      - Template-based and tab-based field navigation
      - Clipboard-paste for reliable data entry
      - Per-row error handling with retry
      - Graceful teardown
    """

    # ------------------------------------------------------------------ #
    #  WorkflowBase Properties                                            #
    # ------------------------------------------------------------------ #

    @property
    def name(self) -> str:
        return "erp_data_entry"

    @property
    def description(self) -> str:
        return ("Automates entry of invoice/purchase records from a spreadsheet "
                "into a generic ERP application using mouse, keyboard, and "
                "template-based UI detection.")

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def required_config(self) -> List[str]:
        # app_path is optional (ERP may already be open)
        return []

    @property
    def required_columns(self) -> List[str]:
        # No required column names — the user maps any columns via the UI
        return []

    # ------------------------------------------------------------------ #
    #  Lifecycle                                                           #
    # ------------------------------------------------------------------ #

    def setup(self, context: Any) -> None:
        """Launch the ERP application (if configured) and navigate to entry screen."""
        super().setup(context)
        cfg = context.config

        app_path = cfg.get("app_path")
        window_title = cfg.get("app_window_title", "ERP")
        entry_mode = cfg.get("entry_mode", "tab")

        self.log_step("ERP Data Entry setup (mode=%s)", entry_mode)

        # Launch application if a path is provided
        if app_path:
            with StepContext("Launch ERP Application", context.errors):
                self._launch_application(app_path, context)
                context.wait.sleep(cfg.get("app_launch_delay", 3.0))

        # Wait for the application window to be ready
        if cfg.get("new_record_template"):
            with StepContext("Wait for ERP ready", context.errors):
                context.wait_for(
                    cfg["new_record_template"],
                    label="New Record Button",
                    timeout=cfg.get("app_ready_timeout", 30.0)
                )
                self.log_step("ERP application is ready")
        else:
            # No template — just wait a moment for the app to settle
            context.wait.medium_pause()
            self.log_step("ERP application assumed ready (no template configured)")

    def process_row(self, row: Dict[str, Any], context: Any) -> WorkflowResult:
        """
        Enter one row of data into the ERP application.

        Steps:
          1. Click "New Record" (or equivalent)
          2. Fill each field in order
          3. Click "Save" (or press Ctrl+S)
          4. Verify save succeeded
          5. Return WorkflowResult
        """
        cfg = context.config
        row_idx = row.get("_row_index", 0)
        max_retries = cfg.get("max_retries", 2)

        for attempt in range(1, max_retries + 2):
            try:
                result = self._enter_record(row, context)
                return result
            except Exception as e:
                if attempt <= max_retries:
                    self.log_warning("Row %d attempt %d failed: %s — retrying",
                                     row_idx, attempt, e)
                    context.wait.sleep(1.0 * attempt)
                    # Try to dismiss any error dialogs before retrying
                    self._dismiss_dialogs(context)
                else:
                    return WorkflowResult(
                        row_index=row_idx,
                        success=False,
                        error=str(e)
                    )

    def teardown(self, context: Any, summary: WorkflowSummary) -> None:
        """Save any pending changes and optionally close the application."""
        cfg = context.config
        self.log_step("Teardown: %d/%d rows succeeded", summary.succeeded, summary.total)

        # Save any unsaved state
        if cfg.get("save_on_teardown", True):
            try:
                context.input.hotkey("ctrl", "s")
                context.wait.short_pause()
            except Exception:
                pass

        # Close application if we launched it
        if cfg.get("close_on_teardown", False) and cfg.get("app_path"):
            try:
                context.input.hotkey("alt", "F4")
                context.wait.short_pause()
            except Exception:
                pass

        super().teardown(context, summary)

    def on_row_error(self, row: Dict[str, Any], error: Exception,
                     context: Any) -> bool:
        """Log the error and continue with the next row."""
        self.log_warning("Skipping row %s due to error: %s",
                         row.get("_row_index", "?"), error)
        self._dismiss_dialogs(context)
        return True  # Continue

    def on_complete(self, summary: WorkflowSummary, context: Any) -> None:
        """Log the final summary."""
        self.log_step(
            "ERP Data Entry complete: %d/%d rows entered successfully "
            "(%.1f%% success rate, %.1fs total)",
            summary.succeeded, summary.total,
            summary.success_rate * 100, summary.duration
        )
        if summary.failed_rows():
            self.log_warning("Failed rows: %s",
                             [r.row_index for r in summary.failed_rows()])

    # ------------------------------------------------------------------ #
    #  Private Implementation                                             #
    # ------------------------------------------------------------------ #

    def _enter_record(self, row: Dict[str, Any], context: Any) -> WorkflowResult:
        """Core logic for entering one record into the ERP."""
        cfg = context.config
        entry_mode = cfg.get("entry_mode", "tab")
        row_idx = row.get("_row_index", 0)

        # Step 1: Open a new record
        with StepContext("Open New Record", context.errors):
            self._open_new_record(context)

        # Step 2: Fill fields
        with StepContext(f"Fill Fields (row {row_idx})", context.errors):
            if entry_mode == "template":
                self._fill_fields_by_template(row, context)
            elif entry_mode == "ocr":
                self._fill_fields_by_ocr(row, context)
            else:  # "tab" (default)
                self._fill_fields_by_tab(row, context)

        # Step 3: Save the record
        with StepContext("Save Record", context.errors):
            self._save_record(context)

        # Step 4: Verify save
        with StepContext("Verify Save", context.errors, raise_on_error=False):
            self._verify_save(context)

        # Inter-row delay
        context.wait.sleep(cfg.get("inter_row_delay", 0.5))

        return WorkflowResult(
            row_index=row_idx,
            success=True,
            data={"invoice_number": row.get("invoice_number", "")}
        )

    def _open_new_record(self, context: Any) -> None:
        """Click the 'New Record' button or use a keyboard shortcut."""
        cfg = context.config
        template = cfg.get("new_record_template")
        shortcut = cfg.get("new_record_shortcut", "ctrl+n")

        if template:
            element = context.find(template, label="New Record Button")
            if element:
                context.click_element(element)
                context.wait.short_pause()
                return

        # Fallback: keyboard shortcut
        keys = shortcut.split("+")
        context.input.hotkey(*keys)
        context.wait.short_pause()
        self.log_debug("Opened new record via shortcut: %s", shortcut)

    def _fill_fields_by_tab(self, row: Dict[str, Any], context: Any) -> None:
        """
        Fill fields by navigating with the Tab key.

        The field_order config key defines which row fields to enter
        and in what order. Each field is entered using clipboard paste
        for reliability.
        """
        cfg = context.config
        field_order = cfg.get("field_order", [
            "invoice_number",
            "vendor_name",
            "invoice_date",
            "amount",
            "description",
            "cost_center",
            "purchase_order"
        ])

        # Click on the first field to ensure focus
        first_field_template = cfg.get("first_field_template")
        if first_field_template:
            element = context.find(first_field_template, label="First Field")
            if element:
                context.click_element(element)
                context.wait.short_pause()

        for i, field_name in enumerate(field_order):
            value = row.get(field_name, "")
            if value is None or str(value).strip() == "" or str(value).lower() == "nan":
                # Empty field — just tab past it without typing
                context.input.tab()
                continue

            self.log_debug("Filling field '%s' = %r", field_name, str(value)[:30])
            context.type_into_field(value, clear_first=True)
            context.input.tab()
            context.wait.sleep(0.05)

    def _fill_fields_by_template(self, row: Dict[str, Any], context: Any) -> None:
        """
        Fill fields by clicking on each field using template matching.

        Requires template images for each field in the config:
          field_templates:
            invoice_number: templates/field_invoice_number.png
            vendor_name: templates/field_vendor_name.png
            ...
        """
        cfg = context.config
        field_templates = cfg.get("field_templates", {})

        fields_to_fill = [
            ("invoice_number", row.get("invoice_number", "")),
            ("vendor_name", row.get("vendor_name", "")),
            ("invoice_date", row.get("invoice_date", "")),
            ("amount", row.get("amount", "")),
            ("description", row.get("description", "")),
            ("cost_center", row.get("cost_center", "")),
            ("purchase_order", row.get("purchase_order", "")),
        ]

        for field_name, value in fields_to_fill:
            if not value or str(value).strip() == "" or str(value).lower() == "nan":
                continue

            template_path = field_templates.get(field_name)
            if not template_path:
                self.log_debug("No template for field '%s', skipping", field_name)
                continue

            element = context.find(template_path, label=f"Field: {field_name}")
            if not element:
                if field_name in self.required_columns:
                    raise ElementNotFoundError(
                        f"Required field template not found: {field_name}"
                    )
                continue

            # Click slightly to the right of the label (into the input box)
            cx, cy = element.center
            context.input.click(cx + element.width + 10, cy)
            context.wait.sleep(0.1)
            context.type_into_field(value, clear_first=True)
            self.log_debug("Filled field '%s' via template", field_name)

    def _fill_fields_by_ocr(self, row: Dict[str, Any], context: Any) -> None:
        """
        Fill fields by finding their labels on screen via OCR.

        Looks for text labels like "Invoice Number:", "Vendor:", etc.
        and clicks to the right of each label to enter the input field.
        """
        cfg = context.config
        label_map = cfg.get("field_labels", {
            "invoice_number": "Invoice Number",
            "vendor_name": "Vendor",
            "invoice_date": "Date",
            "amount": "Amount",
            "description": "Description",
            "cost_center": "Cost Center",
            "purchase_order": "PO Number",
        })
        click_offset_x = cfg.get("label_click_offset_x", 150)

        fields_to_fill = [
            ("invoice_number", row.get("invoice_number", "")),
            ("vendor_name", row.get("vendor_name", "")),
            ("invoice_date", row.get("invoice_date", "")),
            ("amount", row.get("amount", "")),
            ("description", row.get("description", "")),
            ("cost_center", row.get("cost_center", "")),
            ("purchase_order", row.get("purchase_order", "")),
        ]

        for field_name, value in fields_to_fill:
            if not value or str(value).strip() == "" or str(value).lower() == "nan":
                continue

            label_text = label_map.get(field_name)
            if not label_text:
                continue

            element = context.find_text(label_text, label=f"Label: {label_text}")
            if not element:
                if field_name in self.required_columns:
                    raise ElementNotFoundError(
                        f"Required field label not found via OCR: {label_text!r}"
                    )
                continue

            # Click to the right of the label to focus the input field
            cx, cy = element.center
            context.input.click(cx + click_offset_x, cy)
            context.wait.sleep(0.1)
            context.type_into_field(value, clear_first=True)
            self.log_debug("Filled field '%s' via OCR label", field_name)

    def _save_record(self, context: Any) -> None:
        """Save the current record via button click or keyboard shortcut."""
        cfg = context.config
        save_template = cfg.get("save_template")
        save_shortcut = cfg.get("save_shortcut", "ctrl+s")

        if save_template:
            element = context.find(save_template, label="Save Button")
            if element:
                context.click_element(element)
                context.wait.short_pause()
                return

        # Fallback: keyboard shortcut
        keys = save_shortcut.split("+")
        context.input.hotkey(*keys)
        context.wait.short_pause()
        self.log_debug("Saved record via shortcut: %s", save_shortcut)

    def _verify_save(self, context: Any) -> bool:
        """
        Verify that the record was saved successfully.

        Checks for:
          1. A success indicator template (if configured)
          2. Absence of an error dialog
          3. Screen stability (form reset to empty state)
        """
        cfg = context.config
        success_template = cfg.get("success_indicator_template")
        error_template = cfg.get("error_dialog_template")

        # Check for error dialog
        if error_template:
            screen = context.capture()
            error_el = context.vision.find_template(
                screen, error_template, label="Error Dialog"
            )
            if error_el:
                raise Exception("Error dialog detected after save")

        # Check for success indicator
        if success_template:
            try:
                context.wait_for(
                    success_template,
                    label="Save Success",
                    timeout=cfg.get("save_timeout", 10.0)
                )
                return True
            except Exception:
                self.log_warning("Save success indicator not found")
                return False

        # Default: wait for screen to stabilize
        context.wait.wait_for_stable_screen(
            capture_fn=context.capture,
            stable_duration=0.5,
            timeout=cfg.get("save_timeout", 10.0)
        )
        return True

    def _dismiss_dialogs(self, context: Any) -> None:
        """Attempt to dismiss any open error dialogs."""
        cfg = context.config
        dismiss_template = cfg.get("dismiss_dialog_template")

        if dismiss_template:
            screen = context.capture()
            el = context.vision.find_template(screen, dismiss_template)
            if el:
                context.click_element(el)
                context.wait.short_pause()
                return

        # Try pressing Escape to dismiss
        context.input.escape()
        context.wait.short_pause()

    def _launch_application(self, app_path: str, context: Any) -> None:
        """Launch the ERP application as a subprocess."""
        self.log_step("Launching application: %s", app_path)
        subprocess.Popen([app_path], env={**__import__("os").environ,
                                          "DISPLAY": context.config.get("display", ":99")})
