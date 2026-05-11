# Desktop Automation Agent

A **modular, reusable desktop operator platform** built in Python. It controls the mouse and keyboard, reads spreadsheets, detects UI elements, interacts with desktop and browser applications, and executes multi-step workflows — all with robust error handling and crash recovery.

The system is designed as a **general-purpose automation platform**, not a single-purpose bot. New workflows are added by dropping a single Python file into the `workflows/` directory, with zero changes to the core.

---

## Architecture

```
desktop_agent/
├── core/                        # Platform kernel
│   ├── input_controller.py      # Mouse & keyboard control (pyautogui)
│   ├── screen_capture.py        # Fast screenshots (mss + OpenCV)
│   ├── vision.py                # UI detection: template matching + OCR
│   ├── wait_handler.py          # Polling, timeouts, screen stability
│   └── error_handler.py        # Retry decorator, StepContext, safe execute
│
├── data/                        # Data layer
│   ├── spreadsheet_reader.py    # Excel/CSV reader with row iteration
│   ├── clipboard_manager.py     # Clipboard copy/paste with state preservation
│   └── data_mapper.py           # Column → field mapping with transforms
│
├── engine/                      # Workflow engine
│   ├── agent_context.py         # Shared runtime context (all components)
│   ├── workflow_base.py         # Abstract base class for workflow plugins
│   ├── workflow_engine.py       # Orchestrator: load, run, resume, summarize
│   └── logger_setup.py          # Structured logging (console + file + JSON)
│
├── workflows/                   # Workflow plugins (add new ones here)
│   ├── erp_data_entry.py        # ERP data entry (reference implementation)
│   └── browser_form_filler.py   # Web form filler (second example)
│
├── config/                      # YAML configuration files
│   └── erp_data_entry.yaml      # Sample ERP workflow config
│
├── data/                        # Sample data files
│   └── sample_invoices.xlsx     # 10-row sample invoice data
│
├── templates/                   # UI template images (screenshots of buttons)
├── logs/                        # Runtime logs and error screenshots
├── tests/                       # Integration test suite (42 tests)
├── docs/                        # Developer documentation
├── main.py                      # CLI entry point
└── requirements.txt
```

---

## Quick Start

### 1. Install Dependencies

```bash
sudo pip3 install -r requirements.txt
```

### 2. List Available Workflows

```bash
python3 main.py list
```

### 3. Run the ERP Data Entry Workflow

```bash
python3 main.py run erp_data_entry data/sample_invoices.xlsx \
    --config config/erp_data_entry.yaml
```

### 4. Resume After a Crash

```bash
python3 main.py run erp_data_entry data/sample_invoices.xlsx \
    --config config/erp_data_entry.yaml --resume
```

### 5. Dry Run (Validate Without Executing)

```bash
python3 main.py run erp_data_entry data/sample_invoices.xlsx \
    --config config/erp_data_entry.yaml --dry-run
```

---

## Core Capabilities

| Capability | Module | Description |
|---|---|---|
| Mouse control | `InputController` | Move, click, double-click, drag, scroll |
| Keyboard control | `InputController` | Type, hotkeys, Tab navigation, Ctrl+C/V |
| Fast clipboard paste | `InputController` + `ClipboardManager` | Handles Unicode, special chars, long strings |
| Screen capture | `ScreenCapture` | Full screen or region, 60fps capable |
| Template matching | `Vision` | Find buttons/icons by screenshot template |
| OCR text detection | `Vision` | Find text labels on screen via Tesseract |
| Pixel color detection | `Vision` | Detect status indicators by color |
| Polling waits | `WaitHandler` | Wait for element, disappear, stable screen |
| Retry with backoff | `ErrorHandler` | `@retry` decorator with exponential backoff |
| Safe step execution | `ErrorHandler` | `StepContext` — logs, times, screenshots on error |
| Spreadsheet reading | `SpreadsheetReader` | Excel/CSV, multi-sheet, resume from row |
| Data mapping | `DataMapper` | Column → field with transforms and validation |
| Workflow plugins | `WorkflowBase` | Drop-in plugins, auto-discovered |
| Progress tracking | `WorkflowEngine` | JSON progress file for crash recovery |
| Structured logging | `logger_setup` | Console (colored) + file + JSON log |

---

## ERP Data Entry Workflow

The `erp_data_entry` workflow is the reference implementation. It supports three field-navigation modes:

| Mode | How It Works | Best For |
|---|---|---|
| `tab` | Navigates fields using the Tab key | Most desktop ERP apps |
| `template` | Finds each field by a screenshot of its label | Apps with consistent layouts |
| `ocr` | Finds each field by reading its text label | Apps where templates are impractical |

**Configuration** (`config/erp_data_entry.yaml`):

```yaml
entry_mode: "tab"
field_order: [invoice_number, vendor_name, invoice_date, amount, description]
new_record_shortcut: "ctrl+n"
save_shortcut: "ctrl+s"
max_retries: 2
```

---

## Adding a New Workflow

Create a file in `workflows/` — it will be auto-discovered:

```python
# workflows/my_workflow.py
from engine.workflow_base import WorkflowBase, WorkflowResult
from core.error_handler import StepContext

class MyWorkflow(WorkflowBase):
    @property
    def name(self): return "my_workflow"

    @property
    def description(self): return "Does something useful."

    @property
    def required_columns(self): return ["id", "value"]

    def setup(self, context):
        # Open the application, navigate to the right screen, etc.
        pass

    def process_row(self, row, context) -> WorkflowResult:
        with StepContext("Enter ID", context.errors):
            context.type_into_field(row["id"])
            context.input.tab()

        with StepContext("Enter Value", context.errors):
            context.type_into_field(row["value"])
            context.input.enter()

        return WorkflowResult(row["_row_index"], success=True)

    def teardown(self, context, summary):
        # Clean up, close app, etc.
        pass
```

Run it:

```bash
python3 main.py run my_workflow data/my_data.xlsx
```

---

## The `AgentContext` Object

Every workflow method receives `context`, which provides access to all platform components:

```python
context.input          # InputController — mouse and keyboard
context.screen         # ScreenCapture — screenshots
context.vision         # Vision — template matching and OCR
context.wait           # WaitHandler — polling and timeouts
context.clipboard      # ClipboardManager — copy/paste
context.errors         # ErrorHandler — safe execution
context.config         # Dict — merged configuration

# Convenience methods:
context.find("templates/btn.png")           # → UIElement or None
context.wait_for("templates/btn.png")       # → UIElement (blocks until found)
context.find_and_click("templates/btn.png") # → bool
context.type_into_field("value")            # Clear field + clipboard paste
context.find_text("Submit")                 # → UIElement via OCR
```

---

## Error Handling

The platform provides three levels of error handling:

**1. `@retry` decorator** — Retry a function with exponential backoff:
```python
from core.error_handler import retry

@retry(max_attempts=3, delay=1.0, backoff=2.0)
def click_save():
    context.find_and_click("templates/save.png")
```

**2. `StepContext`** — Log, time, and screenshot on error:
```python
with StepContext("Fill Invoice Number", context.errors):
    context.type_into_field(row["invoice_number"])
    # If this raises, a debug screenshot is saved automatically
```

**3. `safe_execute`** — Run an action without raising:
```python
success, result = context.errors.safe_execute(
    lambda: context.find_and_click("templates/optional_btn.png"),
    description="Optional button click",
    save_screenshot=False
)
```

---

## Running Tests

```bash
cd desktop_agent
DISPLAY=:99 python3 tests/test_platform.py
# Ran 42 tests in ~3s — OK
```

---

## Supported Platforms

| Platform | Status | Notes |
|---|---|---|
| Linux (Ubuntu 22.04+) | Fully supported | Requires Xvfb for headless operation |
| macOS | Supported | Set `display: ""` in config |
| Windows | Supported | Set `display: ""` in config |

---

## Dependencies

| Package | Purpose |
|---|---|
| `pyautogui` | Mouse and keyboard control |
| `mss` | High-performance screen capture |
| `opencv-python-headless` | Template matching and image processing |
| `pytesseract` | OCR text detection |
| `pandas` + `openpyxl` | Spreadsheet reading |
| `pyperclip` | Clipboard management |
| `python-statemachine` | Workflow state management |
| `pyyaml` | Configuration files |
| `click` | CLI interface |
| `rich` | Colored console output |
