#!/usr/bin/env python3
"""
Desktop Automation Agent — CLI Runner

Entry point for the platform. Provides a command-line interface to:
  - List available workflows
  - Run a workflow against a data file
  - Dry-run a workflow (validate data/config without executing)
  - Resume a crashed workflow

Usage:
  python3 main.py list
  python3 main.py run erp_data_entry data/invoices.xlsx --config config.yaml
  python3 main.py run erp_data_entry data/invoices.xlsx --resume
"""

import os
import sys
import yaml
import click
from rich.console import Console
from rich.table import Table

# Ensure the local directory is in the Python path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from engine.logger_setup import setup_logging
from engine.agent_context import AgentContext
from engine.workflow_engine import WorkflowEngine

console = Console()


def load_config(config_path: str) -> dict:
    """Load configuration from a YAML file."""
    if not config_path:
        return {}
    if not os.path.exists(config_path):
        console.print(f"[red]Error: Config file not found: {config_path}[/red]")
        sys.exit(1)
    try:
        with open(config_path, "r") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        console.print(f"[red]Error parsing config file: {e}[/red]")
        sys.exit(1)


@click.group()
def cli():
    """Desktop Automation Agent — Modular Workflow Runner."""
    pass


@cli.command("list")
def list_workflows():
    """List all registered workflow plugins."""
    context = AgentContext(display=":99", debug_screenshots=False)
    engine = WorkflowEngine(context)
    engine.register_all_from_directory()

    workflows = engine.list_workflows()

    table = Table(title="Available Workflows")
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Version", style="magenta")
    table.add_column("Description", style="green")

    for wf in workflows:
        table.add_row(wf["name"], wf["version"], wf["description"])

    console.print(table)


@cli.command("run")
@click.argument("workflow_name")
@click.argument("data_file")
@click.option("--config", "-c", help="Path to YAML configuration file.")
@click.option("--resume", is_flag=True, help="Resume from the last completed row.")
@click.option("--start-row", type=int, default=0, help="Row index to start from.")
@click.option("--dry-run", is_flag=True, help="Validate data and config, but do not execute.")
@click.option("--log-level", default="INFO", type=click.Choice(["DEBUG", "INFO", "WARNING"]), help="Logging level.")
@click.option("--display", default=":99", help="X Display to use (default: :99 for headless).")
def run_workflow(workflow_name, data_file, config, resume, start_row, dry_run, log_level, display):
    """
    Run a workflow against a data file.

    WORKFLOW_NAME: Name of the workflow plugin (e.g., 'erp_data_entry').
    DATA_FILE: Path to the Excel or CSV file containing the data.
    """
    setup_logging(log_level=log_level, workflow_name=workflow_name)

    # Load YAML config
    cfg_dict = load_config(config)

    # Initialize Platform
    context = AgentContext(config=cfg_dict, display=display)
    engine = WorkflowEngine(context)
    engine.register_all_from_directory()

    # Determine start row
    actual_start_row = start_row
    if resume:
        actual_start_row = engine.get_resume_row(workflow_name, data_file)
        if actual_start_row > 0:
            console.print(f"[yellow]Resuming workflow from row {actual_start_row}[/yellow]")

    try:
        summary = engine.run(
            workflow_name=workflow_name,
            data_file=data_file,
            config=cfg_dict,
            start_row=actual_start_row,
            dry_run=dry_run
        )

        if dry_run:
            console.print("[green]Dry run complete. No errors found.[/green]")
        else:
            console.print(f"\n[bold green]Workflow Complete: {summary.succeeded}/{summary.total} rows successful.[/bold green]")
            if summary.failed_rows():
                console.print(f"[bold red]Failed rows: {[r.row_index for r in summary.failed_rows()]}[/bold red]")

    except Exception as e:
        console.print(f"[bold red]Workflow execution failed: {e}[/bold red]")
        sys.exit(1)
    finally:
        context.close()


if __name__ == "__main__":
    cli()
