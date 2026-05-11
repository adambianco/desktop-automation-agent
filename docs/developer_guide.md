# Desktop Automation Agent - Developer Guide

The Desktop Automation Agent is a modular, Python-based platform for building robust desktop automation workflows. It provides a core set of reliable primitives for controlling the mouse and keyboard, capturing the screen, detecting UI elements, reading data, and handling errors.

## 1. Architecture Overview

The system is divided into four main layers:

1. **Core Platform (`core/`)**: Wraps low-level libraries (`pyautogui`, `mss`, `opencv`, `pytesseract`) to provide safe, logged, and robust primitives.
2. **Data Layer (`data/`)**: Handles reading spreadsheets (`pandas`), clipboard management (`pyperclip`), and mapping data columns to workflow variables.
3. **Workflow Engine (`engine/`)**: Orchestrates the execution of workflows, handles plugin discovery, manages state, and provides crash recovery.
4. **Workflow Plugins (`workflows/`)**: User-defined modules that implement specific automation tasks (e.g., ERP data entry).

## 2. Core Components

### 2.1 InputController (`core/input_controller.py`)
Handles all mouse and keyboard operations. It is configured with a default `typing_interval` and `move_duration` to simulate human interaction.
*Key features:* `type_text_clipboard()` for fast, reliable data entry that avoids Unicode/special character issues.

### 2.2 ScreenCapture (`core/screen_capture.py`)
Uses `mss` for high-performance screen capture. Returns NumPy arrays (BGR) ready for OpenCV processing.

### 2.3 Vision (`core/vision.py`)
Provides two detection strategies:
*   **Template Matching**: Finds UI elements (buttons, icons) using OpenCV `matchTemplate`.
*   **OCR**: Finds text labels on the screen using Tesseract (`pytesseract`).

### 2.4 WaitHandler (`core/wait_handler.py`)
Replaces hardcoded `time.sleep()` with robust polling.
*Key methods:* `wait_for_element()`, `wait_for_stable_screen()`.

### 2.5 ErrorHandler (`core/error_handler.py`)
Provides the `@retry` decorator and the `StepContext` context manager. It automatically captures screenshots when an error occurs to aid debugging.

## 3. Building a New Workflow

To add a new workflow, simply create a new `.py` file in the `workflows/` directory. The engine will automatically discover it.

### Step 1: Subclass `WorkflowBase`
```python
from engine.workflow_base import WorkflowBase, WorkflowResult
from core.error_handler import StepContext

class MyCustomWorkflow(WorkflowBase):
    @property
    def name(self) -> str:
        return "my_custom_workflow"

    @property
    def description(self) -> str:
        return "Does something awesome."

    @property
    def required_columns(self) -> list:
        return ["id", "amount"]
```

### Step 2: Implement Lifecycle Methods
*   `setup(context)`: Run once before processing rows (e.g., launch app).
*   `process_row(row, context)`: Run for every row in the spreadsheet.
*   `teardown(context, summary)`: Run once after all rows are processed.

```python
    def process_row(self, row, context) -> WorkflowResult:
        with StepContext("Enter ID", context.errors):
            context.type_into_field(row["id"])
            context.input.tab()

        with StepContext("Enter Amount", context.errors):
            context.type_into_field(row["amount"])
            context.input.enter()

        return WorkflowResult(row.get("_row_index", 0), success=True)
```

## 4. The `AgentContext` Object

Every workflow method receives the `AgentContext` object. This is your gateway to the platform. It holds instantiated, configured versions of all core components:

*   `context.input`: The `InputController`
*   `context.screen`: The `ScreenCapture`
*   `context.vision`: The `Vision` module
*   `context.wait`: The `WaitHandler`
*   `context.clipboard`: The `ClipboardManager`
*   `context.config`: The merged configuration dictionary

**Convenience Methods:**
*   `context.find("templates/btn.png")` -> UIElement
*   `context.wait_for("templates/btn.png")` -> UIElement
*   `context.find_and_click("templates/btn.png")` -> bool
*   `context.type_into_field("value")`

## 5. Configuration

Workflows are configured via YAML files passed to the CLI.

```yaml
# config.yaml
display: ":99"
typing_interval: 0.05
max_retries: 3

# Workflow-specific settings
app_path: "/usr/bin/my_app"
entry_mode: "tab"
```

## 6. Running the Agent

Use the CLI to list and run workflows:

```bash
# List workflows
python3 main.py list

# Run a workflow
python3 main.py run erp_data_entry data.xlsx --config config.yaml

# Resume after a crash
python3 main.py run erp_data_entry data.xlsx --config config.yaml --resume
```
