"""
Integration Test Suite — Desktop Automation Agent Platform

Tests all major components without requiring a real display or application.
Uses mocking and synthetic data to validate the full pipeline.
"""

import os
import sys
import json
import time
import unittest
import tempfile
import numpy as np
from unittest.mock import MagicMock, patch, call
from io import StringIO

# Ensure the project root is in the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# ============================================================
# Test: DataMapper
# ============================================================
class TestDataMapper(unittest.TestCase):
    def setUp(self):
        from data.data_mapper import DataMapper, FieldMapping
        self.DataMapper = DataMapper
        self.FieldMapping = FieldMapping

    def test_basic_mapping(self):
        mapper = self.DataMapper([
            self.FieldMapping("Invoice #", "invoice_number"),
            self.FieldMapping("Vendor", "vendor_name"),
            self.FieldMapping("Amount", "amount"),
        ])
        row = {"Invoice #": "INV-001", "Vendor": "Acme Corp", "Amount": "1500.00"}
        result = mapper.map(row)
        self.assertEqual(result["invoice_number"], "INV-001")
        self.assertEqual(result["vendor_name"], "Acme Corp")
        self.assertEqual(result["amount"], "1500.00")

    def test_default_value(self):
        mapper = self.DataMapper([
            self.FieldMapping("Notes", "notes", default="N/A"),
        ])
        row = {"Notes": ""}
        result = mapper.map(row)
        self.assertEqual(result["notes"], "N/A")

    def test_transform_date(self):
        mapper = self.DataMapper([
            self.FieldMapping("Date", "date",
                              transform=self.DataMapper.format_date("%d/%m/%Y")),
        ])
        row = {"Date": "2026-05-08"}
        result = mapper.map(row)
        self.assertEqual(result["date"], "08/05/2026")

    def test_transform_currency(self):
        mapper = self.DataMapper([
            self.FieldMapping("Amount", "amount",
                              transform=lambda v: self.DataMapper.format_currency(v, 2)),
        ])
        row = {"Amount": "1500"}
        result = mapper.map(row)
        self.assertEqual(result["amount"], "1500.00")

    def test_required_field_raises(self):
        mapper = self.DataMapper([
            self.FieldMapping("Invoice #", "invoice_number", required=True),
        ])
        row = {"Invoice #": ""}
        with self.assertRaises(ValueError):
            mapper.map(row)

    def test_strip_and_upper_transform(self):
        mapper = self.DataMapper([
            self.FieldMapping("Code", "code",
                              transform=self.DataMapper.strip_and_upper),
        ])
        row = {"Code": "  abc-123  "}
        result = mapper.map(row)
        self.assertEqual(result["code"], "ABC-123")

    def test_map_all_with_skip_errors(self):
        mapper = self.DataMapper([
            self.FieldMapping("ID", "id", required=True),
        ])
        rows = [
            {"ID": "001", "_row_index": 0},
            {"ID": "",    "_row_index": 1},  # Will fail
            {"ID": "003", "_row_index": 2},
        ]
        results = mapper.map_all(rows, skip_errors=True)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["id"], "001")
        self.assertEqual(results[1]["id"], "003")


# ============================================================
# Test: SpreadsheetReader
# ============================================================
class TestSpreadsheetReader(unittest.TestCase):
    def setUp(self):
        import openpyxl
        import pandas as pd
        self.tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        self.tmp.close()

        # Create a test Excel file
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Invoice #", "Vendor", "Amount", "Date"])
        ws.append(["INV-001", "Acme Corp", 1500.00, "2026-01-15"])
        ws.append(["INV-002", "Beta Ltd",  2300.50, "2026-02-20"])
        ws.append(["INV-003", "Gamma Inc", 750.00,  "2026-03-10"])
        wb.save(self.tmp.name)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_load_and_count(self):
        from data.spreadsheet_reader import SpreadsheetReader
        reader = SpreadsheetReader(self.tmp.name)
        reader.load()
        self.assertEqual(reader.row_count, 3)

    def test_columns(self):
        from data.spreadsheet_reader import SpreadsheetReader
        reader = SpreadsheetReader(self.tmp.name)
        reader.load()
        self.assertIn("Invoice #", reader.columns)
        self.assertIn("Vendor", reader.columns)

    def test_iter_rows(self):
        from data.spreadsheet_reader import SpreadsheetReader
        reader = SpreadsheetReader(self.tmp.name)
        reader.load()
        rows = list(reader.iter_rows())
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["Invoice #"], "INV-001")
        self.assertEqual(rows[0]["_row_index"], 0)

    def test_start_row(self):
        from data.spreadsheet_reader import SpreadsheetReader
        reader = SpreadsheetReader(self.tmp.name)
        reader.load()
        rows = list(reader.iter_rows(start_row=1))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["Invoice #"], "INV-002")

    def test_column_map(self):
        from data.spreadsheet_reader import SpreadsheetReader
        reader = SpreadsheetReader(self.tmp.name)
        reader.load(column_map={"Invoice #": "invoice_number"})
        self.assertIn("invoice_number", reader.columns)

    def test_validate_columns(self):
        from data.spreadsheet_reader import SpreadsheetReader
        reader = SpreadsheetReader(self.tmp.name)
        reader.load()
        missing = reader.validate_columns(["Invoice #", "NonExistent"])
        self.assertEqual(missing, ["NonExistent"])

    def test_file_not_found(self):
        from data.spreadsheet_reader import SpreadsheetReader
        with self.assertRaises(FileNotFoundError):
            SpreadsheetReader("/nonexistent/path.xlsx")


# ============================================================
# Test: ClipboardManager
# ============================================================
class TestClipboardManager(unittest.TestCase):
    def test_copy_and_paste(self):
        from data.clipboard_manager import ClipboardManager
        cb = ClipboardManager()
        cb.copy("Hello World")
        self.assertEqual(cb.paste(), "Hello World")

    def test_preserve_restores_content(self):
        from data.clipboard_manager import ClipboardManager
        cb = ClipboardManager()
        cb.copy("Original Content")
        with cb.preserve():
            cb.copy("Temporary Content")
            self.assertEqual(cb.paste(), "Temporary Content")
        self.assertEqual(cb.paste(), "Original Content")

    def test_history(self):
        from data.clipboard_manager import ClipboardManager
        cb = ClipboardManager(history_size=5)
        for i in range(3):
            cb.copy(f"item_{i}")
        history = cb.get_history()
        self.assertEqual(len(history), 3)
        self.assertEqual(history[-1], "item_2")

    def test_float_conversion(self):
        from data.clipboard_manager import ClipboardManager
        cb = ClipboardManager()
        result = cb._to_string(1500.0)
        self.assertEqual(result, "1500")

    def test_none_conversion(self):
        from data.clipboard_manager import ClipboardManager
        cb = ClipboardManager()
        self.assertEqual(cb._to_string(None), "")


# ============================================================
# Test: ErrorHandler
# ============================================================
class TestErrorHandler(unittest.TestCase):
    def test_retry_decorator_succeeds_on_second_attempt(self):
        from core.error_handler import retry
        call_count = {"n": 0}

        @retry(max_attempts=3, delay=0.01)
        def flaky_fn():
            call_count["n"] += 1
            if call_count["n"] < 2:
                raise ValueError("Transient error")
            return "success"

        result = flaky_fn()
        self.assertEqual(result, "success")
        self.assertEqual(call_count["n"], 2)

    def test_retry_decorator_raises_after_max_attempts(self):
        from core.error_handler import retry
        @retry(max_attempts=2, delay=0.01)
        def always_fails():
            raise RuntimeError("Always fails")

        with self.assertRaises(RuntimeError):
            always_fails()

    def test_safe_execute_returns_false_on_error(self):
        from core.error_handler import ErrorHandler
        eh = ErrorHandler(debug_dir="/tmp/test_errors")
        success, result = eh.safe_execute(
            lambda: 1 / 0,
            description="division by zero",
            save_screenshot=False
        )
        self.assertFalse(success)
        self.assertIsNone(result)

    def test_safe_execute_returns_true_on_success(self):
        from core.error_handler import ErrorHandler
        eh = ErrorHandler(debug_dir="/tmp/test_errors")
        success, result = eh.safe_execute(
            lambda: 42,
            description="answer",
            save_screenshot=False
        )
        self.assertTrue(success)
        self.assertEqual(result, 42)

    def test_assert_element_found_raises(self):
        from core.error_handler import ErrorHandler, ElementNotFoundError
        eh = ErrorHandler(debug_dir="/tmp/test_errors")
        with self.assertRaises(ElementNotFoundError):
            eh.assert_element_found(None, "Test Element")

    def test_step_context_logs_success(self):
        from core.error_handler import ErrorHandler, StepContext
        eh = ErrorHandler(debug_dir="/tmp/test_errors")
        with StepContext("Test Step", eh) as ctx:
            pass  # No error
        self.assertTrue(ctx.success)

    def test_step_context_handles_error(self):
        from core.error_handler import ErrorHandler, StepContext
        eh = ErrorHandler(debug_dir="/tmp/test_errors")
        with StepContext("Failing Step", eh, raise_on_error=False) as ctx:
            raise ValueError("Intentional error")
        self.assertFalse(ctx.success)
        self.assertIsNotNone(ctx.error)


# ============================================================
# Test: Vision (no display required — uses synthetic images)
# ============================================================
class TestVision(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def _make_test_image(self, width=400, height=300, color=(200, 200, 200)):
        """Create a synthetic BGR screen image."""
        img = np.full((height, width, 3), color, dtype=np.uint8)
        return img

    def _make_template(self, width=50, height=30, color=(100, 150, 200)):
        """Create a synthetic template image and save it."""
        import cv2
        template = np.full((height, width, 3), color, dtype=np.uint8)
        path = os.path.join(self.tmp_dir, "test_template.png")
        cv2.imwrite(path, template)
        return path, template

    def test_find_template_success(self):
        from core.vision import Vision
        import cv2

        # Create a screen with a known pattern embedded
        screen = self._make_test_image(400, 300)
        template_path, template = self._make_template(50, 30, (100, 150, 200))

        # Embed the template at a known location
        screen[100:130, 150:200] = template

        vision = Vision(template_dir=self.tmp_dir)
        result = vision.find_template(screen, template_path, label="Test Button",
                                      threshold=0.90)
        self.assertIsNotNone(result)
        self.assertEqual(result.label, "Test Button")
        self.assertGreater(result.confidence, 0.90)

    def test_find_template_not_found(self):
        from core.vision import Vision
        import cv2

        # Screen: complex gradient pattern
        screen = np.zeros((300, 400, 3), dtype=np.uint8)
        for i in range(300):
            screen[i, :] = [i % 256, (i * 2) % 256, (i * 3) % 256]

        # Template: completely different pattern (white noise on black background)
        template = np.zeros((30, 50, 3), dtype=np.uint8)
        template[10:20, 20:40] = [255, 0, 0]  # Red rectangle
        template_path = os.path.join(self.tmp_dir, "red_template.png")
        cv2.imwrite(template_path, template)

        vision = Vision(template_dir=self.tmp_dir)
        # The red-on-black template should not match the gradient screen at 0.95 threshold
        result = vision.find_template(screen, template_path, threshold=0.95)
        self.assertIsNone(result)

    def test_uielement_center(self):
        from core.vision import UIElement
        el = UIElement(label="btn", x=100, y=200, width=80, height=40)
        self.assertEqual(el.center, (140, 220))

    def test_uielement_rect(self):
        from core.vision import UIElement
        el = UIElement(label="btn", x=10, y=20, width=60, height=30)
        self.assertEqual(el.rect, (10, 20, 60, 30))

    def test_pixel_color(self):
        from core.vision import Vision
        vision = Vision()
        screen = np.zeros((100, 100, 3), dtype=np.uint8)
        screen[50, 50] = [0, 128, 255]  # BGR: blue=0, green=128, red=255
        r, g, b = vision.get_pixel_color(screen, 50, 50)
        self.assertEqual(r, 255)
        self.assertEqual(g, 128)
        self.assertEqual(b, 0)


# ============================================================
# Test: WaitHandler
# ============================================================
class TestWaitHandler(unittest.TestCase):
    def test_poll_until_succeeds(self):
        from core.wait_handler import WaitHandler
        wh = WaitHandler(default_timeout=5.0, default_poll_interval=0.1)
        counter = {"n": 0}

        def condition():
            counter["n"] += 1
            return counter["n"] >= 3

        result = wh.poll_until(condition, description="counter >= 3")
        self.assertTrue(result)
        self.assertEqual(counter["n"], 3)

    def test_poll_until_timeout_raises(self):
        from core.wait_handler import WaitHandler, TimeoutError
        wh = WaitHandler(default_timeout=0.3, default_poll_interval=0.1)
        with self.assertRaises(TimeoutError):
            wh.poll_until(lambda: False, description="never true")

    def test_poll_until_timeout_no_raise(self):
        from core.wait_handler import WaitHandler
        wh = WaitHandler(default_timeout=0.3, default_poll_interval=0.1)
        result = wh.poll_until(lambda: False, description="never",
                                raise_on_timeout=False)
        self.assertIsNone(result)


# ============================================================
# Test: WorkflowBase and WorkflowResult
# ============================================================
class TestWorkflowBase(unittest.TestCase):
    def test_workflow_result(self):
        from engine.workflow_base import WorkflowResult
        r = WorkflowResult(row_index=5, success=True, data={"id": "001"})
        self.assertEqual(r.row_index, 5)
        self.assertTrue(r.success)

    def test_workflow_summary(self):
        from engine.workflow_base import WorkflowResult, WorkflowSummary
        summary = WorkflowSummary("test_workflow")
        summary.add(WorkflowResult(0, True))
        summary.add(WorkflowResult(1, True))
        summary.add(WorkflowResult(2, False, error="boom"))
        summary.finish()

        self.assertEqual(summary.total, 3)
        self.assertEqual(summary.succeeded, 2)
        self.assertEqual(summary.failed, 1)
        self.assertAlmostEqual(summary.success_rate, 2/3, places=5)
        self.assertEqual(len(summary.failed_rows()), 1)

    def test_erp_workflow_properties(self):
        from workflows.erp_data_entry import ERPDataEntryWorkflow
        wf = ERPDataEntryWorkflow()
        self.assertEqual(wf.name, "erp_data_entry")
        self.assertIn("invoice_number", wf.required_columns)

    def test_browser_workflow_properties(self):
        from workflows.browser_form_filler import BrowserFormFillerWorkflow
        wf = BrowserFormFillerWorkflow()
        self.assertEqual(wf.name, "browser_form_filler")
        self.assertIn("url", wf.required_config)


# ============================================================
# Test: WorkflowEngine (mocked context)
# ============================================================
class TestWorkflowEngine(unittest.TestCase):
    def _make_mock_context(self):
        ctx = MagicMock()
        ctx.config = {}
        ctx.state = {}
        return ctx

    def test_register_and_list(self):
        from engine.workflow_engine import WorkflowEngine
        from workflows.erp_data_entry import ERPDataEntryWorkflow

        ctx = self._make_mock_context()
        engine = WorkflowEngine(ctx)
        engine.register_workflow(ERPDataEntryWorkflow)

        workflows = engine.list_workflows()
        names = [w["name"] for w in workflows]
        self.assertIn("erp_data_entry", names)

    def test_run_dry_run(self):
        import openpyxl
        from engine.workflow_engine import WorkflowEngine
        from workflows.erp_data_entry import ERPDataEntryWorkflow

        # Create a minimal test spreadsheet
        tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        tmp.close()
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["invoice_number", "vendor_name", "invoice_date", "amount"])
        ws.append(["INV-001", "Acme", "2026-01-01", "1000"])
        wb.save(tmp.name)

        ctx = self._make_mock_context()
        engine = WorkflowEngine(ctx)
        engine.register_workflow(ERPDataEntryWorkflow)

        try:
            summary = engine.run(
                "erp_data_entry",
                tmp.name,
                config={},
                dry_run=True
            )
            self.assertEqual(summary.total, 0)  # Dry run: no rows processed
        finally:
            os.unlink(tmp.name)

    def test_unregistered_workflow_raises(self):
        from engine.workflow_engine import WorkflowEngine
        ctx = self._make_mock_context()
        engine = WorkflowEngine(ctx)
        with self.assertRaises(ValueError):
            engine.run("nonexistent_workflow", "data.xlsx")


# ============================================================
# Test: ERP Workflow process_row (fully mocked)
# ============================================================
class TestERPWorkflowProcessRow(unittest.TestCase):
    def _make_context(self):
        ctx = MagicMock()
        ctx.config = {
            "entry_mode": "tab",
            "max_retries": 0,
            "inter_row_delay": 0.0,
            "save_on_teardown": False,
        }
        ctx.state = {}
        ctx.errors = MagicMock()
        ctx.errors.__class__ = type("ErrorHandler", (), {
            "_save_error_screenshot": lambda *a: None
        })
        # Make StepContext work
        from core.error_handler import ErrorHandler
        ctx.errors = ErrorHandler(debug_dir="/tmp/test_errors")
        ctx.capture = MagicMock(return_value=np.zeros((100, 100, 3), dtype=np.uint8))
        ctx.vision = MagicMock()
        ctx.vision.find_template = MagicMock(return_value=None)
        ctx.input = MagicMock()
        ctx.wait = MagicMock()
        ctx.clipboard = MagicMock()
        ctx.clipboard.preserve = MagicMock(return_value=MagicMock(
            __enter__=lambda s: s,
            __exit__=lambda s, *a: None
        ))
        ctx.find = MagicMock(return_value=None)
        ctx.find_text = MagicMock(return_value=None)
        ctx.wait_for = MagicMock(return_value=None)
        ctx.type_into_field = MagicMock()
        ctx.click_element = MagicMock()
        return ctx

    def test_process_row_tab_mode(self):
        from workflows.erp_data_entry import ERPDataEntryWorkflow
        wf = ERPDataEntryWorkflow()
        ctx = self._make_context()

        row = {
            "_row_index": 0,
            "invoice_number": "INV-001",
            "vendor_name": "Acme Corp",
            "invoice_date": "2026-01-15",
            "amount": "1500.00",
            "description": "Test invoice",
            "cost_center": "",
            "purchase_order": "",
        }

        result = wf.process_row(row, ctx)
        self.assertTrue(result.success)
        self.assertEqual(result.row_index, 0)


# ============================================================
# Run all tests
# ============================================================
if __name__ == "__main__":
    # Set up minimal logging for test output
    import logging
    logging.basicConfig(level=logging.WARNING)

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    test_classes = [
        TestDataMapper,
        TestSpreadsheetReader,
        TestClipboardManager,
        TestErrorHandler,
        TestVision,
        TestWaitHandler,
        TestWorkflowBase,
        TestWorkflowEngine,
        TestERPWorkflowProcessRow,
    ]

    for tc in test_classes:
        suite.addTests(loader.loadTestsFromTestCase(tc))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
