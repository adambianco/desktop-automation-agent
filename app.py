"""
Desktop Automation Agent — GUI Application
==========================================
A polished, user-friendly desktop app that lets anyone run automation
workflows without touching the command line.

Run with:
  python app.py          (Windows: double-click Run Desktop Agent.bat)
"""

import os
import sys
import json
import queue
import logging
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
import tkinter.ttk as ttk

# Ensure project root is on path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

_HAS_CTK = False  # Using standard tkinter for maximum compatibility

import yaml

# ── Logging bridge ────────────────────────────────────────────────────────────

class QueueHandler(logging.Handler):
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        self.log_queue.put(self.format(record))


# ── Colours ───────────────────────────────────────────────────────────────────

DARK_BG      = "#1a1a2e"
PANEL_BG     = "#16213e"
ACCENT       = "#0f3460"
HIGHLIGHT    = "#e94560"
TEXT_PRIMARY = "#eaeaea"
TEXT_DIM     = "#8888aa"
SUCCESS      = "#4caf50"
WARNING_COL  = "#ff9800"
ERROR_COL    = "#f44336"
LOG_BG       = "#0d0d1a"


# ── Main Application ──────────────────────────────────────────────────────────

class DesktopAgentApp:

    def __init__(self):
        self.root = ctk.CTk() if _HAS_CTK else tk.Tk()
        self.root.title("Desktop Automation Agent")
        self.root.geometry("1100x750")
        self.root.minsize(900, 600)
        if not _HAS_CTK:
            self.root.configure(bg=DARK_BG)

        self.log_queue = queue.Queue()
        self.run_thread = None
        self._stop_event = threading.Event()
        self._workflow_registry = {}
        self._data_file = ""
        self._config_widgets = {}

        self._setup_logging()
        self._discover_workflows()
        self._build_ui()
        self.root.after(100, self._poll_log_queue)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()

    # ── Logging ──────────────────────────────────────────────────────────────

    def _setup_logging(self):
        os.makedirs("logs", exist_ok=True)
        fmt = logging.Formatter("%(asctime)s [%(levelname)-8s] %(message)s", datefmt="%H:%M:%S")
        q_handler = QueueHandler(self.log_queue)
        q_handler.setFormatter(fmt)
        q_handler.setLevel(logging.DEBUG)
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        root_logger.handlers.clear()
        root_logger.addHandler(q_handler)
        fh = logging.FileHandler("logs/desktop_agent.log", encoding="utf-8")
        fh.setFormatter(fmt)
        fh.setLevel(logging.DEBUG)
        root_logger.addHandler(fh)

    # ── Workflow Discovery ────────────────────────────────────────────────────

    def _discover_workflows(self):
        import importlib.util
        workflows_dir = os.path.join(os.path.dirname(__file__), "workflows")
        if not os.path.isdir(workflows_dir):
            return
        try:
            from engine.workflow_base import WorkflowBase
        except ImportError:
            return
        for filename in sorted(os.listdir(workflows_dir)):
            if not filename.endswith(".py") or filename.startswith("_"):
                continue
            module_path = os.path.join(workflows_dir, filename)
            try:
                spec = importlib.util.spec_from_file_location(filename[:-3], module_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (isinstance(attr, type) and
                            issubclass(attr, WorkflowBase) and
                            attr is not WorkflowBase):
                        instance = attr()
                        self._workflow_registry[instance.name] = {
                            "class": attr,
                            "instance": instance,
                            "description": instance.description,
                            "required_columns": instance.required_columns,
                            "required_config": instance.required_config,
                        }
            except Exception as e:
                logging.warning("Could not load workflow %s: %s", filename, e)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.root.grid_columnconfigure(0, weight=0, minsize=320)
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_rowconfigure(1, weight=0)
        self._build_sidebar()
        self._build_main_panel()
        self._build_status_bar()

    def _build_sidebar(self):
        if _HAS_CTK:
            sidebar = ctk.CTkScrollableFrame(self.root, width=310, fg_color=PANEL_BG, corner_radius=0)
        else:
            sidebar = tk.Frame(self.root, bg=PANEL_BG, width=310)
        sidebar.grid(row=0, column=0, sticky="nsew")
        if not _HAS_CTK:
            sidebar.grid_propagate(False)

        title_frame = tk.Frame(sidebar, bg=ACCENT, pady=16)
        title_frame.pack(fill="x")
        tk.Label(title_frame, text="⚙  Desktop Agent", font=("Segoe UI", 15, "bold"),
                 fg=TEXT_PRIMARY, bg=ACCENT).pack()
        tk.Label(title_frame, text="Automation Platform", font=("Segoe UI", 9),
                 fg=TEXT_DIM, bg=ACCENT).pack()

        pad = {"padx": 16, "pady": 4}

        self._section_label(sidebar, "WORKFLOW")
        workflow_names = list(self._workflow_registry.keys()) or ["(no workflows found)"]
        self.workflow_var = tk.StringVar(value=workflow_names[0])
        if _HAS_CTK:
            self.workflow_menu = ctk.CTkOptionMenu(
                sidebar, values=workflow_names, variable=self.workflow_var,
                command=self._on_workflow_change,
                fg_color=ACCENT, button_color=HIGHLIGHT, font=("Segoe UI", 11))
            self.workflow_menu.pack(fill="x", **pad)
        else:
            self.workflow_menu = ttk.Combobox(sidebar, textvariable=self.workflow_var,
                                              values=workflow_names, state="readonly")
            self.workflow_menu.pack(fill="x", **pad)
            self.workflow_menu.bind("<<ComboboxSelected>>", lambda e: self._on_workflow_change(None))

        self.workflow_desc = tk.Label(sidebar, text="", wraplength=270,
                                      font=("Segoe UI", 9), fg=TEXT_DIM, bg=PANEL_BG, justify="left")
        self.workflow_desc.pack(fill="x", padx=16, pady=(0, 8))

        self._section_label(sidebar, "DATA FILE  (.xlsx / .csv)")
        file_frame = tk.Frame(sidebar, bg=PANEL_BG)
        file_frame.pack(fill="x", **pad)
        self.file_label = tk.Label(file_frame, text="No file selected",
                                   font=("Segoe UI", 9), fg=TEXT_DIM, bg=PANEL_BG,
                                   anchor="w", wraplength=200)
        self.file_label.pack(side="left", fill="x", expand=True)
        self._button(file_frame, "Browse", self._browse_file, small=True).pack(side="right")

        self.cols_label = tk.Label(sidebar, text="", wraplength=270,
                                   font=("Segoe UI", 8), fg=TEXT_DIM, bg=PANEL_BG, justify="left")
        self.cols_label.pack(fill="x", padx=16, pady=(0, 4))

        self._section_label(sidebar, "SETTINGS")
        self._settings_frame = tk.Frame(sidebar, bg=PANEL_BG)
        self._settings_frame.pack(fill="x", padx=16, pady=4)
        self._build_settings_fields()

        cfg_frame = tk.Frame(sidebar, bg=PANEL_BG)
        cfg_frame.pack(fill="x", padx=16, pady=8)
        self._button(cfg_frame, "Load Config", self._load_config_file, small=True).pack(side="left", padx=(0, 4))
        self._button(cfg_frame, "Save Config", self._save_config_file, small=True).pack(side="left")

        self._section_label(sidebar, "CONTROLS")
        ctrl_frame = tk.Frame(sidebar, bg=PANEL_BG)
        ctrl_frame.pack(fill="x", padx=16, pady=8)
        self.run_btn = self._button(ctrl_frame, "▶  Run", self._run_workflow, color=SUCCESS)
        self.run_btn.pack(fill="x", pady=(0, 6))
        self.stop_btn = self._button(ctrl_frame, "■  Stop", self._stop_workflow, color=ERROR_COL)
        self.stop_btn.pack(fill="x")
        self.stop_btn.configure(state="disabled")

        self.dry_run_var = tk.BooleanVar(value=False)
        tk.Checkbutton(sidebar, text="Dry run (validate only, don't click)",
                       variable=self.dry_run_var, font=("Segoe UI", 9),
                       fg=TEXT_DIM, bg=PANEL_BG, selectcolor=ACCENT,
                       activebackground=PANEL_BG, activeforeground=TEXT_PRIMARY
                       ).pack(anchor="w", padx=16, pady=2)

        self.resume_var = tk.BooleanVar(value=False)
        tk.Checkbutton(sidebar, text="Resume from last completed row",
                       variable=self.resume_var, font=("Segoe UI", 9),
                       fg=TEXT_DIM, bg=PANEL_BG, selectcolor=ACCENT,
                       activebackground=PANEL_BG, activeforeground=TEXT_PRIMARY
                       ).pack(anchor="w", padx=16, pady=2)

        self._on_workflow_change(workflow_names[0])

    def _build_main_panel(self):
        if _HAS_CTK:
            main = ctk.CTkFrame(self.root, fg_color=DARK_BG, corner_radius=0)
        else:
            main = tk.Frame(self.root, bg=DARK_BG)
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_rowconfigure(2, weight=1)
        main.grid_columnconfigure(0, weight=1)

        header = tk.Frame(main, bg=ACCENT, pady=10, padx=20)
        header.grid(row=0, column=0, sticky="ew")
        tk.Label(header, text="Live Execution Log", font=("Segoe UI", 13, "bold"),
                 fg=TEXT_PRIMARY, bg=ACCENT).pack(side="left")
        self._button(header, "Clear Log", self._clear_log, small=True).pack(side="right")

        prog_frame = tk.Frame(main, bg=DARK_BG, pady=8, padx=20)
        prog_frame.grid(row=1, column=0, sticky="ew")
        prog_frame.grid_columnconfigure(1, weight=1)
        tk.Label(prog_frame, text="Progress:", font=("Segoe UI", 9),
                 fg=TEXT_DIM, bg=DARK_BG).grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.progress_var = tk.DoubleVar(value=0)
        if _HAS_CTK:
            self.progress_bar = ctk.CTkProgressBar(prog_frame, variable=self.progress_var,
                                                    progress_color=HIGHLIGHT)
            self.progress_bar.grid(row=0, column=1, sticky="ew")
        else:
            self.progress_bar = ttk.Progressbar(prog_frame, variable=self.progress_var, maximum=100)
            self.progress_bar.grid(row=0, column=1, sticky="ew")
        self.progress_label = tk.Label(prog_frame, text="0 / 0 rows",
                                       font=("Segoe UI", 9), fg=TEXT_DIM, bg=DARK_BG)
        self.progress_label.grid(row=0, column=2, padx=(8, 0))

        log_frame = tk.Frame(main, bg=LOG_BG)
        log_frame.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 10))
        log_frame.grid_rowconfigure(0, weight=1)
        log_frame.grid_columnconfigure(0, weight=1)
        self.log_text = tk.Text(log_frame, bg=LOG_BG, fg=TEXT_PRIMARY,
                                font=("Consolas", 9), wrap="word", state="disabled",
                                relief="flat", insertbackground=TEXT_PRIMARY,
                                selectbackground=ACCENT)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.tag_configure("INFO",     foreground="#aaffaa")
        self.log_text.tag_configure("DEBUG",    foreground="#888899")
        self.log_text.tag_configure("WARNING",  foreground="#ffcc44")
        self.log_text.tag_configure("ERROR",    foreground="#ff5555")
        self.log_text.tag_configure("CRITICAL", foreground="#ff0000", font=("Consolas", 9, "bold"))
        self.log_text.tag_configure("SUCCESS",  foreground="#44ff88", font=("Consolas", 9, "bold"))

    def _build_status_bar(self):
        bar = tk.Frame(self.root, bg=ACCENT, height=28)
        bar.grid(row=1, column=0, columnspan=2, sticky="ew")
        bar.grid_propagate(False)
        self.status_var = tk.StringVar(value="Ready")
        tk.Label(bar, textvariable=self.status_var, font=("Segoe UI", 9),
                 fg=TEXT_PRIMARY, bg=ACCENT, anchor="w", padx=12).pack(side="left", fill="y")
        tk.Label(bar, text="Desktop Automation Agent  v1.0",
                 font=("Segoe UI", 9), fg=TEXT_DIM, bg=ACCENT,
                 anchor="e", padx=12).pack(side="right", fill="y")

    _DEFAULT_SETTINGS = [
        ("entry_mode",          "Entry Mode",                    "tab",       "tab | template | ocr"),
        ("app_path",            "App Path (optional)",           "",          "e.g. C:\\ERP\\app.exe"),
        ("new_record_shortcut", "New Record Shortcut",           "ctrl+n",    ""),
        ("save_shortcut",       "Save Shortcut",                 "ctrl+s",    ""),
        ("field_order",         "Field Order (comma-separated)", "invoice_number,vendor_name,invoice_date,amount,description", ""),
        ("max_retries",         "Max Retries",                   "2",         ""),
        ("inter_row_delay",     "Delay Between Rows (sec)",      "0.5",       ""),
        ("typing_interval",     "Typing Speed (sec/char)",       "0.03",      ""),
    ]

    def _build_settings_fields(self):
        for widget in self._settings_frame.winfo_children():
            widget.destroy()
        self._config_widgets.clear()
        for key, label, default, _ in self._DEFAULT_SETTINGS:
            row = tk.Frame(self._settings_frame, bg=PANEL_BG)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=label, font=("Segoe UI", 9), fg=TEXT_DIM,
                     bg=PANEL_BG, anchor="w", width=22).pack(side="left")
            var = tk.StringVar(value=default)
            tk.Entry(row, textvariable=var, font=("Segoe UI", 9),
                     bg=ACCENT, fg=TEXT_PRIMARY, insertbackground=TEXT_PRIMARY,
                     relief="flat", bd=4).pack(side="left", fill="x", expand=True)
            self._config_widgets[key] = var

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _section_label(self, parent, text):
        tk.Label(parent, text=text, font=("Segoe UI", 8, "bold"),
                 fg=TEXT_DIM, bg=PANEL_BG, anchor="w", padx=16, pady=6).pack(fill="x")

    def _button(self, parent, text, command, color=ACCENT, small=False):
        font = ("Segoe UI", 9) if small else ("Segoe UI", 11, "bold")
        pady = 4 if small else 8
        if _HAS_CTK:
            return ctk.CTkButton(parent, text=text, command=command,
                                 fg_color=color, hover_color=HIGHLIGHT,
                                 font=font, corner_radius=6,
                                 height=28 if small else 36)
        return tk.Button(parent, text=text, command=command,
                         bg=color, fg=TEXT_PRIMARY, font=font,
                         relief="flat", pady=pady, cursor="hand2",
                         activebackground=HIGHLIGHT, activeforeground=TEXT_PRIMARY)

    # ── Events ────────────────────────────────────────────────────────────────

    def _on_workflow_change(self, value):
        name = self.workflow_var.get()
        info = self._workflow_registry.get(name)
        if info:
            self.workflow_desc.configure(text=info["description"])
            cols = info["required_columns"]
            self.cols_label.configure(
                text=f"Required columns: {', '.join(cols)}" if cols else "")
        else:
            self.workflow_desc.configure(text="")
            self.cols_label.configure(text="")

    def _browse_file(self):
        path = filedialog.askopenfilename(
            title="Select Data File",
            filetypes=[("Spreadsheets", "*.xlsx *.xls *.csv"), ("All files", "*.*")])
        if path:
            self._data_file = path
            self.file_label.configure(text=os.path.basename(path), fg=TEXT_PRIMARY)
            self._set_status(f"File: {os.path.basename(path)}")
            self._log(f"Data file: {path}", "INFO")

    def _load_config_file(self):
        path = filedialog.askopenfilename(
            title="Load Configuration",
            filetypes=[("YAML files", "*.yaml *.yml"), ("JSON files", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            with open(path) as f:
                cfg = yaml.safe_load(f) if path.endswith((".yaml", ".yml")) else json.load(f)
            for key, var in self._config_widgets.items():
                if key in cfg:
                    val = cfg[key]
                    var.set(",".join(str(v) for v in val) if isinstance(val, list) else str(val))
            self._log(f"Config loaded: {os.path.basename(path)}", "INFO")
            self._set_status(f"Config loaded: {os.path.basename(path)}")
        except Exception as e:
            messagebox.showerror("Config Error", f"Could not load config:\n{e}")

    def _save_config_file(self):
        path = filedialog.asksaveasfilename(
            title="Save Configuration", defaultextension=".yaml",
            filetypes=[("YAML files", "*.yaml"), ("JSON files", "*.json")])
        if not path:
            return
        cfg = self._collect_config()
        try:
            with open(path, "w") as f:
                yaml.dump(cfg, f, default_flow_style=False) if path.endswith((".yaml", ".yml")) else json.dump(cfg, f, indent=2)
            self._log(f"Config saved: {os.path.basename(path)}", "INFO")
            self._set_status(f"Config saved: {os.path.basename(path)}")
        except Exception as e:
            messagebox.showerror("Save Error", f"Could not save config:\n{e}")

    def _collect_config(self):
        cfg = {}
        for key, var in self._config_widgets.items():
            val = var.get().strip()
            if key == "field_order":
                cfg[key] = [v.strip() for v in val.split(",") if v.strip()]
            elif key == "max_retries":
                try: cfg[key] = int(val)
                except: cfg[key] = 2
            elif key in ("inter_row_delay", "typing_interval"):
                try: cfg[key] = float(val)
                except: cfg[key] = 0.5
            elif val:
                cfg[key] = val
        return cfg

    # ── Run / Stop ────────────────────────────────────────────────────────────

    def _run_workflow(self):
        if self.workflow_var.get() not in self._workflow_registry:
            messagebox.showerror("Error", "Please select a valid workflow.")
            return
        if not self._data_file:
            messagebox.showerror("Error", "Please select a data file first.")
            return
        if not os.path.exists(self._data_file):
            messagebox.showerror("Error", f"Data file not found:\n{self._data_file}")
            return

        self._stop_event.clear()
        self.run_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.progress_var.set(0)
        self.progress_label.configure(text="0 / ? rows")
        self._set_status("Running…")
        self._log(f"Starting: {self.workflow_var.get()}", "INFO")

        self.run_thread = threading.Thread(
            target=self._run_in_thread,
            args=(self.workflow_var.get(), self._data_file,
                  self._collect_config(), self.dry_run_var.get(), self.resume_var.get()),
            daemon=True)
        self.run_thread.start()

    def _run_in_thread(self, workflow_name, data_file, cfg, dry_run, resume):
        try:
            from engine.agent_context import AgentContext
            from engine.workflow_engine import WorkflowEngine
            context = AgentContext(config=cfg)
            engine = WorkflowEngine(context, progress_callback=self._on_progress)
            engine.register_all_from_directory()
            start_row = 0
            if resume:
                start_row = engine.get_resume_row(workflow_name, data_file)
                if start_row > 0:
                    self._log(f"Resuming from row {start_row}", "WARNING")
            summary = engine.run(workflow_name=workflow_name, data_file=data_file,
                                 config=cfg, start_row=start_row, dry_run=dry_run)
            context.close()
            if dry_run:
                self._log("✓ Dry run complete — no errors.", "SUCCESS")
            else:
                self._log(f"✓ Complete: {summary.succeeded}/{summary.total} rows ({summary.duration:.1f}s)", "SUCCESS")
                if summary.failed_rows():
                    self._log(f"✗ Failed rows: {[r.row_index for r in summary.failed_rows()]}", "ERROR")
            self.root.after(0, lambda: self._set_status(f"Complete: {summary.succeeded}/{summary.total} rows"))
        except Exception as e:
            self._log(f"✗ Error: {e}", "ERROR")
            self.root.after(0, lambda: self._set_status(f"Error: {e}"))
        finally:
            self.root.after(0, self._on_run_finished)

    def _on_progress(self, current, total, result):
        pct = (current / total * 100) if total > 0 else 0
        self.root.after(0, lambda: self.progress_var.set(pct))
        self.root.after(0, lambda: self.progress_label.configure(text=f"{current} / {total} rows"))
        level = "INFO" if result.success else "ERROR"
        msg = f"  Row {current}/{total}  {'✓' if result.success else '✗'}  {'OK' if result.success else result.error}"
        self.root.after(0, lambda: self._log(msg, level))

    def _stop_workflow(self):
        self._stop_event.set()
        self._log("Stop requested…", "WARNING")
        self.stop_btn.configure(state="disabled")

    def _on_run_finished(self):
        self.run_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")

    # ── Log ───────────────────────────────────────────────────────────────────

    def _log(self, message, level="INFO"):
        self.log_queue.put(f"[{level}] {message}")

    def _poll_log_queue(self):
        try:
            while True:
                record = self.log_queue.get_nowait()
                self._append_log(record)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_log_queue)

    def _append_log(self, text):
        self.log_text.configure(state="normal")
        tag = "INFO"
        for level in ("DEBUG", "WARNING", "ERROR", "CRITICAL", "SUCCESS"):
            if f"[{level}]" in text:
                tag = level
                break
        self.log_text.insert("end", text + "\n", tag)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _set_status(self, message):
        self.status_var.set(message)

    def _on_close(self):
        if self.run_thread and self.run_thread.is_alive():
            if not messagebox.askyesno("Quit", "A workflow is running. Stop and quit?"):
                return
            self._stop_event.set()
        self.root.destroy()


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    DesktopAgentApp()
