"""
Logger Setup — configures structured, colored logging for the platform.

Provides:
  - Console output with Rich formatting (colored, readable)
  - File output with full structured logs (JSON-friendly)
  - Per-workflow log files
  - Log rotation
"""

import os
import sys
import json
import logging
import logging.handlers
from datetime import datetime
from typing import Optional


class JSONFormatter(logging.Formatter):
    """Formats log records as JSON for machine-readable log files."""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.utcfromtimestamp(record.created).isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_data)


class RichConsoleHandler(logging.StreamHandler):
    """Console handler that uses Rich for colored output."""

    LEVEL_COLORS = {
        "DEBUG":    "\033[90m",    # Dark gray
        "INFO":     "\033[32m",    # Green
        "WARNING":  "\033[33m",    # Yellow
        "ERROR":    "\033[31m",    # Red
        "CRITICAL": "\033[1;31m",  # Bold red
    }
    RESET = "\033[0m"

    def emit(self, record: logging.LogRecord) -> None:
        try:
            color = self.LEVEL_COLORS.get(record.levelname, "")
            msg = self.format(record)
            self.stream.write(f"{color}{msg}{self.RESET}\n")
            self.flush()
        except Exception:
            self.handleError(record)


def setup_logging(log_dir: str = "logs",
                  log_level: str = "INFO",
                  workflow_name: Optional[str] = None,
                  console: bool = True,
                  json_file: bool = True,
                  max_bytes: int = 10 * 1024 * 1024,  # 10 MB
                  backup_count: int = 5) -> logging.Logger:
    """
    Configure the logging system for the desktop automation platform.

    Args:
        log_dir: Directory to store log files.
        log_level: Minimum log level ("DEBUG", "INFO", "WARNING", "ERROR").
        workflow_name: Optional workflow name for per-workflow log files.
        console: Whether to output logs to the console.
        json_file: Whether to write JSON-formatted log files.
        max_bytes: Maximum size of each log file before rotation.
        backup_count: Number of rotated log files to keep.

    Returns:
        The root logger.
    """
    os.makedirs(log_dir, exist_ok=True)
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # Capture everything; handlers filter

    # Remove existing handlers
    root_logger.handlers.clear()

    # --- Console Handler ---
    if console:
        console_handler = RichConsoleHandler(sys.stdout)
        console_handler.setLevel(numeric_level)
        console_fmt = logging.Formatter(
            "%(asctime)s [%(levelname)-8s] %(name)-25s %(message)s",
            datefmt="%H:%M:%S"
        )
        console_handler.setFormatter(console_fmt)
        root_logger.addHandler(console_handler)

    # --- Main Log File (rotating, plain text) ---
    main_log_path = os.path.join(log_dir, "desktop_agent.log")
    file_handler = logging.handlers.RotatingFileHandler(
        main_log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(name)-30s %(funcName)-20s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(file_fmt)
    root_logger.addHandler(file_handler)

    # --- JSON Log File ---
    if json_file:
        json_log_path = os.path.join(log_dir, "desktop_agent.jsonl")
        json_handler = logging.handlers.RotatingFileHandler(
            json_log_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8"
        )
        json_handler.setLevel(logging.DEBUG)
        json_handler.setFormatter(JSONFormatter())
        root_logger.addHandler(json_handler)

    # --- Per-Workflow Log File ---
    if workflow_name:
        safe_name = "".join(c if c.isalnum() else "_" for c in workflow_name)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        wf_log_path = os.path.join(log_dir, f"workflow_{safe_name}_{timestamp}.log")
        wf_handler = logging.FileHandler(wf_log_path, encoding="utf-8")
        wf_handler.setLevel(logging.DEBUG)
        wf_handler.setFormatter(file_fmt)
        # Only log workflow-related messages
        wf_logger = logging.getLogger(f"workflow.{workflow_name}")
        wf_logger.addHandler(wf_handler)

    root_logger.info("Logging initialized (level=%s, log_dir=%s)", log_level, log_dir)
    return root_logger


def get_workflow_logger(workflow_name: str) -> logging.Logger:
    """Get a logger namespaced to a specific workflow."""
    return logging.getLogger(f"workflow.{workflow_name}")
