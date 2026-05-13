"""
Desktop Automation Agent — GUI Application
==========================================
Two modes in one app:

  TAB 1 — Workflow Runner
    Load a spreadsheet, pick a workflow, click Run.
    The agent fills fields row by row.

  TAB 2 — Macro Recorder
    Click Record, perform your task (clicks, typing, keys).
    Click Stop. Name and save it.
    Click Play to replay it — as many times as you want.
    Adjust speed, set repeat count.

Run with:
  python app.py   (or double-click Run Desktop Agent.bat)
"""

import os
import sys
import json
import queue
import logging
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
import tkinter.ttk as ttk

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

import yaml

# ── Colours ───────────────────────────────────────────────────────────────────
DARK_BG      = "#0f1117"
PANEL_BG     = "#16213e"
ACCENT       = "#0f3460"
HIGHLIGHT    = "#e94560"
TEXT_PRIMARY = "#eaeaea"
TEXT_DIM     = "#8888aa"
SUCCESS      = "#4caf50"
WARNING_COL  = "#ff9800"
ERROR_COL    = "#f44336"
LOG_BG       = "#0a0a14"
RECORD_RED   = "#e53935"
TAB_ACTIVE   = "#1a2744"

# ── Logging bridge ────────────────────────────────────────────────────────────
class QueueHandler(logging.Handler):
    def __init__(self, q):
        super().__init__()
        self.q = q
    def emit(self, record):
        self.q.put(self.format(record))


# ── Main Application ──────────────────────────────────────────────────────────
class DesktopAgentApp:

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Desktop Automation Agent")
        self.root.geometry("1150x780")
        self.root.minsize(900, 600)
        self.root.configure(bg=DARK_BG)

        self.log_queue = queue.Queue()
        self._workflow_registry = {}
        self._data_file = ""
        self._config_widgets = {}

        # Workflow run state
        self._wf_run_thread = None
        self._wf_stop_event = threading.Event()

        # Macro state
        self._recorder = None
        self._player = None
        self._macro_stop_event = threading.Event()
        self._macro_thread = None
        self._recording = False
        self._current_macro = None  # loaded macro dict

        self._setup_logging()
        self._discover_workflows()
        self._build_ui()
        self.root.after(100, self._poll_log_queue)
        self.root.after(500, self._start_hotkey_listener)  # Start after UI ready
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
                            "class": attr, "instance": instance,
                            "description": instance.description,
                            "required_columns": instance.required_columns,
                        }
            except Exception as e:
                logging.warning("Could not load workflow %s: %s", filename, e)

    # ── UI Construction ───────────────────────────────────────────────────────
    def _build_ui(self):
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(1, weight=1)

        # Top tab bar
        tab_bar = tk.Frame(self.root, bg=ACCENT, height=44)
        tab_bar.grid(row=0, column=0, sticky="ew")
        tab_bar.grid_propagate(False)

        # Logo
        tk.Label(tab_bar, text="⚙  Desktop Agent",
                 font=("Segoe UI", 12, "bold"),
                 fg=TEXT_PRIMARY, bg=ACCENT).pack(side="left", padx=16)

        # Tab buttons
        self._tab_frame = tk.Frame(self.root, bg=DARK_BG)
        self._tab_frame.grid(row=1, column=0, sticky="nsew")

        self._wf_tab_btn = tk.Button(tab_bar, text="  Workflow Runner  ",
                                      font=("Segoe UI", 10),
                                      bg=TAB_ACTIVE, fg=TEXT_PRIMARY,
                                      relief="flat", bd=0, pady=10,
                                      command=lambda: self._switch_tab("workflow"),
                                      activebackground=HIGHLIGHT,
                                      activeforeground=TEXT_PRIMARY)
        self._wf_tab_btn.pack(side="left")

        self._macro_tab_btn = tk.Button(tab_bar, text="  Macro Recorder  ",
                                         font=("Segoe UI", 10),
                                         bg=ACCENT, fg=TEXT_DIM,
                                         relief="flat", bd=0, pady=10,
                                         command=lambda: self._switch_tab("macro"),
                                         activebackground=HIGHLIGHT,
                                         activeforeground=TEXT_PRIMARY)
        self._macro_tab_btn.pack(side="left")

        # Build both panels
        self._wf_panel = self._build_workflow_panel(self._tab_frame)
        self._macro_panel = self._build_macro_panel(self._tab_frame)

        # Status bar
        status_bar = tk.Frame(self.root, bg=ACCENT, height=26)
        status_bar.grid(row=2, column=0, sticky="ew")
        status_bar.grid_propagate(False)
        self.status_var = tk.StringVar(value="Ready")
        tk.Label(status_bar, textvariable=self.status_var,
                 font=("Segoe UI", 9), fg=TEXT_PRIMARY, bg=ACCENT,
                 anchor="w", padx=12).pack(side="left", fill="y")
        tk.Label(status_bar, text="Desktop Automation Agent  v1.0",
                 font=("Segoe UI", 9), fg=TEXT_DIM, bg=ACCENT,
                 anchor="e", padx=12).pack(side="right", fill="y")

        self._switch_tab("workflow")

    def _switch_tab(self, tab: str):
        if tab == "workflow":
            self._macro_panel.pack_forget()
            self._wf_panel.pack(fill="both", expand=True)
            self._wf_tab_btn.configure(bg=TAB_ACTIVE, fg=TEXT_PRIMARY)
            self._macro_tab_btn.configure(bg=ACCENT, fg=TEXT_DIM)
        else:
            self._wf_panel.pack_forget()
            self._macro_panel.pack(fill="both", expand=True)
            self._macro_tab_btn.configure(bg=TAB_ACTIVE, fg=TEXT_PRIMARY)
            self._wf_tab_btn.configure(bg=ACCENT, fg=TEXT_DIM)
            self._refresh_macro_list()

    # ── Workflow Panel ────────────────────────────────────────────────────────
    def _build_workflow_panel(self, parent):
        panel = tk.Frame(parent, bg=DARK_BG)
        panel.grid_columnconfigure(0, weight=0, minsize=310)
        panel.grid_columnconfigure(1, weight=1)
        panel.grid_rowconfigure(0, weight=1)

        # Sidebar
        sidebar = tk.Frame(panel, bg=PANEL_BG, width=310)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)

        pad = {"padx": 16, "pady": 4}

        self._section_label(sidebar, "WORKFLOW")
        workflow_names = list(self._workflow_registry.keys()) or ["(no workflows found)"]
        self.workflow_var = tk.StringVar(value=workflow_names[0])
        wf_menu = ttk.Combobox(sidebar, textvariable=self.workflow_var,
                                values=workflow_names, state="readonly",
                                font=("Segoe UI", 10))
        wf_menu.pack(fill="x", **pad)
        wf_menu.bind("<<ComboboxSelected>>", lambda e: self._on_workflow_change())

        self.workflow_desc = tk.Label(sidebar, text="", wraplength=270,
                                      font=("Segoe UI", 9), fg=TEXT_DIM,
                                      bg=PANEL_BG, justify="left")
        self.workflow_desc.pack(fill="x", padx=16, pady=(0, 8))

        self._section_label(sidebar, "DATA FILE  (.xlsx / .csv)")
        file_frame = tk.Frame(sidebar, bg=PANEL_BG)
        file_frame.pack(fill="x", **pad)
        self.file_label = tk.Label(file_frame, text="No file selected",
                                   font=("Segoe UI", 9), fg=TEXT_DIM,
                                   bg=PANEL_BG, anchor="w", wraplength=200)
        self.file_label.pack(side="left", fill="x", expand=True)
        self._btn(file_frame, "Browse", self._browse_file, small=True).pack(side="right")

        self.cols_label = tk.Label(sidebar, text="", wraplength=270,
                                   font=("Segoe UI", 8), fg=TEXT_DIM,
                                   bg=PANEL_BG, justify="left")
        self.cols_label.pack(fill="x", padx=16, pady=(0, 4))

        self._section_label(sidebar, "SETTINGS")
        self._settings_frame = tk.Frame(sidebar, bg=PANEL_BG)
        self._settings_frame.pack(fill="x", padx=16, pady=4)
        self._build_settings_fields()

        cfg_frame = tk.Frame(sidebar, bg=PANEL_BG)
        cfg_frame.pack(fill="x", padx=16, pady=8)
        self._btn(cfg_frame, "Load Config", self._load_config_file, small=True).pack(side="left", padx=(0, 4))
        self._btn(cfg_frame, "Save Config", self._save_config_file, small=True).pack(side="left")

        self._section_label(sidebar, "CONTROLS")
        ctrl_frame = tk.Frame(sidebar, bg=PANEL_BG)
        ctrl_frame.pack(fill="x", padx=16, pady=8)
        self.wf_run_btn = self._btn(ctrl_frame, "▶  Run Workflow", self._run_workflow, color=SUCCESS)
        self.wf_run_btn.pack(fill="x", pady=(0, 6))
        self.wf_stop_btn = self._btn(ctrl_frame, "■  Stop", self._stop_workflow, color=ERROR_COL)
        self.wf_stop_btn.pack(fill="x")
        self.wf_stop_btn.configure(state="disabled")

        self.dry_run_var = tk.BooleanVar(value=False)
        tk.Checkbutton(sidebar, text="Dry run (validate only)",
                       variable=self.dry_run_var, font=("Segoe UI", 9),
                       fg=TEXT_DIM, bg=PANEL_BG, selectcolor=ACCENT,
                       activebackground=PANEL_BG, activeforeground=TEXT_PRIMARY
                       ).pack(anchor="w", padx=16, pady=2)
        self.resume_var = tk.BooleanVar(value=False)
        tk.Checkbutton(sidebar, text="Resume from last row",
                       variable=self.resume_var, font=("Segoe UI", 9),
                       fg=TEXT_DIM, bg=PANEL_BG, selectcolor=ACCENT,
                       activebackground=PANEL_BG, activeforeground=TEXT_PRIMARY
                       ).pack(anchor="w", padx=16, pady=2)

        # Main log panel
        main = tk.Frame(panel, bg=DARK_BG)
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_rowconfigure(2, weight=1)
        main.grid_columnconfigure(0, weight=1)

        header = tk.Frame(main, bg=ACCENT, pady=10, padx=20)
        header.grid(row=0, column=0, sticky="ew")
        tk.Label(header, text="Live Execution Log", font=("Segoe UI", 12, "bold"),
                 fg=TEXT_PRIMARY, bg=ACCENT).pack(side="left")
        self._btn(header, "Clear", self._clear_log, small=True).pack(side="right")

        prog_frame = tk.Frame(main, bg=DARK_BG, pady=6, padx=16)
        prog_frame.grid(row=1, column=0, sticky="ew")
        prog_frame.grid_columnconfigure(1, weight=1)
        tk.Label(prog_frame, text="Progress:", font=("Segoe UI", 9),
                 fg=TEXT_DIM, bg=DARK_BG).grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.progress_var = tk.DoubleVar(value=0)
        ttk.Progressbar(prog_frame, variable=self.progress_var, maximum=100
                        ).grid(row=0, column=1, sticky="ew")
        self.progress_label = tk.Label(prog_frame, text="0 / 0 rows",
                                       font=("Segoe UI", 9), fg=TEXT_DIM, bg=DARK_BG)
        self.progress_label.grid(row=0, column=2, padx=(8, 0))

        log_frame = tk.Frame(main, bg=LOG_BG)
        log_frame.grid(row=2, column=0, sticky="nsew", padx=8, pady=(0, 8))
        log_frame.grid_rowconfigure(0, weight=1)
        log_frame.grid_columnconfigure(0, weight=1)
        self.log_text = tk.Text(log_frame, bg=LOG_BG, fg=TEXT_PRIMARY,
                                font=("Consolas", 9), wrap="word", state="disabled",
                                relief="flat", insertbackground=TEXT_PRIMARY)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=sb.set)
        self.log_text.tag_configure("INFO",    foreground="#aaffaa")
        self.log_text.tag_configure("DEBUG",   foreground="#888899")
        self.log_text.tag_configure("WARNING", foreground="#ffcc44")
        self.log_text.tag_configure("ERROR",   foreground="#ff5555")
        self.log_text.tag_configure("SUCCESS", foreground="#44ff88", font=("Consolas", 9, "bold"))

        self._on_workflow_change()
        return panel

    # ── Macro Recorder Panel ──────────────────────────────────────────────────
    def _build_macro_panel(self, parent):
        panel = tk.Frame(parent, bg=DARK_BG)
        panel.grid_columnconfigure(0, weight=0, minsize=310)
        panel.grid_columnconfigure(1, weight=1)
        panel.grid_rowconfigure(0, weight=1)

        # ── Left: controls ──
        left = tk.Frame(panel, bg=PANEL_BG, width=310)
        left.grid(row=0, column=0, sticky="nsew")
        left.grid_propagate(False)

        # Record section
        self._section_label(left, "RECORD A MACRO")
        tk.Label(left, text="1. Press F9 (or click Record)\n2. Perform your task on screen\n3. Press F10 (or click Stop)",
                 font=("Segoe UI", 9), fg=TEXT_DIM, bg=PANEL_BG,
                 justify="left", padx=16).pack(anchor="w", pady=(0, 4))
        tk.Label(left, text="F9 works even when this window is in the background",
                 font=("Segoe UI", 8), fg="#4ade80", bg=PANEL_BG,
                 justify="left", padx=16).pack(anchor="w", pady=(0, 8))

        rec_frame = tk.Frame(left, bg=PANEL_BG)
        rec_frame.pack(fill="x", padx=16, pady=4)
        self.record_btn = self._btn(rec_frame, "⏺  Record", self._start_recording, color=RECORD_RED)
        self.record_btn.pack(fill="x", pady=(0, 6))
        self.stop_rec_btn = self._btn(rec_frame, "⏹  Stop Recording", self._stop_recording, color="#555")
        self.stop_rec_btn.pack(fill="x")
        self.stop_rec_btn.configure(state="disabled")

        # Recording status
        self.rec_status_var = tk.StringVar(value="Not recording")
        self.rec_status_label = tk.Label(left, textvariable=self.rec_status_var,
                                          font=("Consolas", 9), fg=TEXT_DIM, bg=PANEL_BG)
        self.rec_status_label.pack(padx=16, pady=4, anchor="w")

        # Save
        self._section_label(left, "SAVE MACRO")
        save_frame = tk.Frame(left, bg=PANEL_BG)
        save_frame.pack(fill="x", padx=16, pady=4)
        tk.Label(save_frame, text="Name:", font=("Segoe UI", 9),
                 fg=TEXT_DIM, bg=PANEL_BG).pack(side="left")
        self.macro_name_var = tk.StringVar(value="my_macro")
        tk.Entry(save_frame, textvariable=self.macro_name_var,
                 font=("Segoe UI", 9), bg=ACCENT, fg=TEXT_PRIMARY,
                 insertbackground=TEXT_PRIMARY, relief="flat", bd=4
                 ).pack(side="left", fill="x", expand=True, padx=(6, 0))
        self._btn(left, "💾  Save Macro", self._save_macro, small=True).pack(fill="x", padx=16, pady=4)

        # Saved macros list
        self._section_label(left, "SAVED MACROS")
        list_frame = tk.Frame(left, bg=PANEL_BG)
        list_frame.pack(fill="x", padx=16, pady=4)
        self.macro_listbox = tk.Listbox(list_frame, bg=ACCENT, fg=TEXT_PRIMARY,
                                         font=("Segoe UI", 9), relief="flat",
                                         selectbackground=HIGHLIGHT, height=5,
                                         activestyle="none")
        self.macro_listbox.pack(fill="x")
        self.macro_listbox.bind("<<ListboxSelect>>", self._on_macro_select)
        self._btn(left, "📂  Load Selected", self._load_selected_macro, small=True).pack(fill="x", padx=16, pady=(2, 0))
        self._btn(left, "🗑  Delete Selected", self._delete_selected_macro, small=True).pack(fill="x", padx=16, pady=(2, 8))

        # Playback controls
        self._section_label(left, "PLAYBACK")
        play_settings = tk.Frame(left, bg=PANEL_BG)
        play_settings.pack(fill="x", padx=16, pady=4)

        # Speed
        speed_row = tk.Frame(play_settings, bg=PANEL_BG)
        speed_row.pack(fill="x", pady=2)
        tk.Label(speed_row, text="Speed:", font=("Segoe UI", 9),
                 fg=TEXT_DIM, bg=PANEL_BG, width=10, anchor="w").pack(side="left")
        self.speed_var = tk.StringVar(value="1.0")
        speed_options = ["0.25", "0.5", "0.75", "1.0", "1.5", "2.0", "3.0"]
        ttk.Combobox(speed_row, textvariable=self.speed_var, values=speed_options,
                     state="readonly", font=("Segoe UI", 9), width=8).pack(side="left")
        tk.Label(speed_row, text="x", font=("Segoe UI", 9),
                 fg=TEXT_DIM, bg=PANEL_BG).pack(side="left", padx=4)

        # Repeat
        repeat_row = tk.Frame(play_settings, bg=PANEL_BG)
        repeat_row.pack(fill="x", pady=2)
        tk.Label(repeat_row, text="Repeat:", font=("Segoe UI", 9),
                 fg=TEXT_DIM, bg=PANEL_BG, width=10, anchor="w").pack(side="left")
        self.repeat_var = tk.StringVar(value="1")
        tk.Entry(repeat_row, textvariable=self.repeat_var,
                 font=("Segoe UI", 9), bg=ACCENT, fg=TEXT_PRIMARY,
                 insertbackground=TEXT_PRIMARY, relief="flat", bd=4, width=6
                 ).pack(side="left")
        tk.Label(repeat_row, text="times", font=("Segoe UI", 9),
                 fg=TEXT_DIM, bg=PANEL_BG).pack(side="left", padx=4)

        # Loop until stopped
        loop_row = tk.Frame(play_settings, bg=PANEL_BG)
        loop_row.pack(fill="x", pady=4)
        self.loop_var = tk.BooleanVar(value=False)
        tk.Checkbutton(loop_row, text="Loop until stopped  (F6 to stop)",
                       variable=self.loop_var,
                       font=("Segoe UI", 9), fg="#4ade80", bg=PANEL_BG,
                       selectcolor=ACCENT, activebackground=PANEL_BG,
                       activeforeground=TEXT_PRIMARY,
                       command=self._on_loop_toggle).pack(anchor="w")

        # Loop counter (shown during looping)
        self.loop_count_var = tk.StringVar(value="")
        self.loop_count_label = tk.Label(play_settings, textvariable=self.loop_count_var,
                                          font=("Consolas", 9), fg="#4ade80", bg=PANEL_BG)
        self.loop_count_label.pack(anchor="w", pady=(0, 2))

        play_ctrl = tk.Frame(left, bg=PANEL_BG)
        play_ctrl.pack(fill="x", padx=16, pady=8)
        self.play_btn = self._btn(play_ctrl, "▶  Play Macro", self._play_macro, color=SUCCESS)
        self.play_btn.pack(fill="x", pady=(0, 6))
        self.play_btn.configure(state="disabled")
        self.stop_play_btn = self._btn(play_ctrl, "■  Stop Playback  (F6)", self._stop_playback, color=ERROR_COL)
        self.stop_play_btn.pack(fill="x")
        self.stop_play_btn.configure(state="disabled")

        # ── Right: hotkey reference + macro log ──
        right = tk.Frame(panel, bg=DARK_BG)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_rowconfigure(2, weight=1)
        right.grid_columnconfigure(0, weight=1)

        header = tk.Frame(right, bg=ACCENT, pady=10, padx=20)
        header.grid(row=0, column=0, sticky="ew")
        tk.Label(header, text="Macro Event Log", font=("Segoe UI", 12, "bold"),
                 fg=TEXT_PRIMARY, bg=ACCENT).pack(side="left")
        self._btn(header, "Clear", self._clear_macro_log, small=True).pack(side="right")

        # ── Hotkey Reference Card ──
        hotkey_card = tk.Frame(right, bg="#0f1a2e", pady=0)
        hotkey_card.grid(row=1, column=0, sticky="ew", padx=8, pady=(8, 0))

        # Title row
        title_row = tk.Frame(hotkey_card, bg="#0f1a2e")
        title_row.pack(fill="x", padx=14, pady=(10, 6))
        tk.Label(title_row, text="⌨  Keyboard Shortcuts",
                 font=("Segoe UI", 9, "bold"), fg="#60a5fa", bg="#0f1a2e").pack(side="left")
        tk.Label(title_row, text="Work even when app is minimised",
                 font=("Segoe UI", 8), fg="#475569", bg="#0f1a2e").pack(side="right")

        # Hotkey rows
        hotkeys = [
            ("F9",          "Start Recording",   RECORD_RED,  "⏺"),
            ("F10",         "Stop Recording",    "#555",      "⏹"),
            ("F5",          "Play Macro",         SUCCESS,     "▶"),
            ("F6",          "Stop Playback",      ERROR_COL,   "■"),
            ("Esc (corner)","Emergency Stop",     "#f59e0b",   "⚠"),
        ]
        keys_frame = tk.Frame(hotkey_card, bg="#0f1a2e")
        keys_frame.pack(fill="x", padx=14, pady=(0, 10))

        for i, (key, action, color, icon) in enumerate(hotkeys):
            row_bg = "#0d1525" if i % 2 == 0 else "#0f1a2e"
            row = tk.Frame(keys_frame, bg=row_bg)
            row.pack(fill="x", pady=1)
            # Key badge
            tk.Label(row, text=key,
                     font=("Consolas", 9, "bold"),
                     fg=color, bg="#1a2744",
                     padx=8, pady=3, width=14, anchor="center",
                     relief="flat").pack(side="left", padx=(4, 8), pady=2)
            # Icon + action
            tk.Label(row, text=f"{icon}  {action}",
                     font=("Segoe UI", 9),
                     fg=TEXT_PRIMARY, bg=row_bg,
                     anchor="w").pack(side="left", fill="x", expand=True, pady=2)

        macro_log_frame = tk.Frame(right, bg=LOG_BG)
        macro_log_frame.grid(row=2, column=0, sticky="nsew", padx=8, pady=8)
        macro_log_frame.grid_rowconfigure(0, weight=1)
        macro_log_frame.grid_columnconfigure(0, weight=1)

        self.macro_log = tk.Text(macro_log_frame, bg=LOG_BG, fg=TEXT_PRIMARY,
                                  font=("Consolas", 9), wrap="word", state="disabled",
                                  relief="flat")
        self.macro_log.grid(row=0, column=0, sticky="nsew")
        msb = ttk.Scrollbar(macro_log_frame, command=self.macro_log.yview)
        msb.grid(row=0, column=1, sticky="ns")
        self.macro_log.configure(yscrollcommand=msb.set)
        self.macro_log.tag_configure("click",   foreground="#60a5fa")
        self.macro_log.tag_configure("key",     foreground="#a78bfa")
        self.macro_log.tag_configure("move",    foreground="#475569")
        self.macro_log.tag_configure("success", foreground="#4ade80", font=("Consolas", 9, "bold"))
        self.macro_log.tag_configure("info",    foreground="#94a3b8")

        return panel

    # ── Settings Fields ───────────────────────────────────────────────────────
    _DEFAULT_SETTINGS = [
        ("entry_mode",          "Entry Mode",                    "tab"),
        ("app_path",            "App Path (optional)",           ""),
        ("new_record_shortcut", "New Record Shortcut",           "ctrl+n"),
        ("save_shortcut",       "Save Shortcut",                 "ctrl+s"),
        ("field_order",         "Field Order (comma-sep)",       "invoice_number,vendor_name,invoice_date,amount"),
        ("max_retries",         "Max Retries",                   "2"),
        ("inter_row_delay",     "Delay Between Rows (sec)",      "0.5"),
        ("typing_interval",     "Typing Speed (sec/char)",       "0.03"),
    ]

    def _build_settings_fields(self):
        for w in self._settings_frame.winfo_children():
            w.destroy()
        self._config_widgets.clear()
        for key, label, default in self._DEFAULT_SETTINGS:
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
                 fg=TEXT_DIM, bg=PANEL_BG, anchor="w",
                 padx=16, pady=6).pack(fill="x")

    def _btn(self, parent, text, command, color=ACCENT, small=False):
        font = ("Segoe UI", 9) if small else ("Segoe UI", 10, "bold")
        pady = 4 if small else 7
        return tk.Button(parent, text=text, command=command,
                         bg=color, fg=TEXT_PRIMARY, font=font,
                         relief="flat", pady=pady, cursor="hand2",
                         activebackground=HIGHLIGHT, activeforeground=TEXT_PRIMARY)

    # ── Workflow Events ───────────────────────────────────────────────────────
    def _on_workflow_change(self):
        name = self.workflow_var.get()
        info = self._workflow_registry.get(name)
        if info:
            self.workflow_desc.configure(text=info["description"])
            cols = info["required_columns"]
            self.cols_label.configure(text=f"Required columns: {', '.join(cols)}" if cols else "")

    def _browse_file(self):
        path = filedialog.askopenfilename(
            title="Select Data File",
            filetypes=[("Spreadsheets", "*.xlsx *.xls *.csv"), ("All files", "*.*")])
        if path:
            self._data_file = path
            self.file_label.configure(text=os.path.basename(path), fg=TEXT_PRIMARY)
            self._set_status(f"File: {os.path.basename(path)}")

    def _load_config_file(self):
        path = filedialog.askopenfilename(
            title="Load Config", filetypes=[("YAML", "*.yaml *.yml"), ("JSON", "*.json")])
        if not path:
            return
        try:
            with open(path) as f:
                cfg = yaml.safe_load(f) if path.endswith((".yaml", ".yml")) else json.load(f)
            for key, var in self._config_widgets.items():
                if key in cfg:
                    val = cfg[key]
                    var.set(",".join(str(v) for v in val) if isinstance(val, list) else str(val))
            self._set_status(f"Config loaded: {os.path.basename(path)}")
        except Exception as e:
            messagebox.showerror("Error", f"Could not load config:\n{e}")

    def _save_config_file(self):
        path = filedialog.asksaveasfilename(
            title="Save Config", defaultextension=".yaml",
            filetypes=[("YAML", "*.yaml"), ("JSON", "*.json")])
        if not path:
            return
        cfg = self._collect_config()
        try:
            with open(path, "w") as f:
                yaml.dump(cfg, f) if path.endswith((".yaml", ".yml")) else json.dump(cfg, f, indent=2)
            self._set_status(f"Config saved: {os.path.basename(path)}")
        except Exception as e:
            messagebox.showerror("Error", f"Could not save config:\n{e}")

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

    def _run_workflow(self):
        # Guard: don't run workflow while recording a macro
        if self._recording:
            messagebox.showwarning(
                "Recording Active",
                "Please stop macro recording before running a workflow."
            )
            return
        if self.workflow_var.get() not in self._workflow_registry:
            messagebox.showerror("Error", "Please select a valid workflow.")
            return
        if not self._data_file:
            messagebox.showerror("Error", "Please select a data file first.")
            return
        self._wf_stop_event.clear()
        self.wf_run_btn.configure(state="disabled")
        self.wf_stop_btn.configure(state="normal")
        self.progress_var.set(0)
        self._set_status("Running workflow…")
        self._log(f"Starting: {self.workflow_var.get()}", "INFO")
        self._wf_run_thread = threading.Thread(
            target=self._run_workflow_thread,
            args=(self.workflow_var.get(), self._data_file,
                  self._collect_config(), self.dry_run_var.get(), self.resume_var.get()),
            daemon=True)
        self._wf_run_thread.start()

    def _run_workflow_thread(self, workflow_name, data_file, cfg, dry_run, resume):
        try:
            from engine.agent_context import AgentContext
            from engine.workflow_engine import WorkflowEngine
            context = AgentContext(config=cfg)
            engine = WorkflowEngine(context, progress_callback=self._on_wf_progress)
            engine.register_all_from_directory()
            start_row = engine.get_resume_row(workflow_name, data_file) if resume else 0
            summary = engine.run(workflow_name=workflow_name, data_file=data_file,
                                 config=cfg, start_row=start_row, dry_run=dry_run)
            context.close()
            msg = f"✓ Complete: {summary.succeeded}/{summary.total} rows ({summary.duration:.1f}s)"
            self._log(msg, "SUCCESS")
            self.root.after(0, lambda: self._set_status(msg))
        except Exception as e:
            self._log(f"✗ Error: {e}", "ERROR")
            self.root.after(0, lambda: self._set_status(f"Error: {e}"))
        finally:
            self.root.after(0, lambda: (
                self.wf_run_btn.configure(state="normal"),
                self.wf_stop_btn.configure(state="disabled")
            ))

    def _on_wf_progress(self, current, total, result):
        pct = (current / total * 100) if total > 0 else 0
        self.root.after(0, lambda: self.progress_var.set(pct))
        self.root.after(0, lambda: self.progress_label.configure(text=f"{current} / {total} rows"))
        level = "INFO" if result.success else "ERROR"
        msg = f"  Row {current}/{total}  {'✓' if result.success else '✗'}  {'OK' if result.success else result.error}"
        self.root.after(0, lambda: self._log(msg, level))

    def _stop_workflow(self):
        self._wf_stop_event.set()
        self._set_status("Stopping…")
        self.wf_stop_btn.configure(state="disabled")

    # ── Macro Events ──────────────────────────────────────────────────────────
    def _show_recording_indicator(self):
        """
        Show a small always-on-top red dot in the bottom-right corner.
        Pulses to show recording is active. Updates event count live.
        Stays visible even when the main app is minimised.
        """
        if hasattr(self, '_rec_indicator') and self._rec_indicator:
            return  # Already showing

        ind = tk.Toplevel(self.root)
        ind.overrideredirect(True)       # No title bar or borders
        ind.attributes("-topmost", True) # Always on top of everything
        ind.attributes("-alpha", 0.92)
        ind.configure(bg="#0a0e1a")
        ind.resizable(False, False)

        # Position: bottom-right corner, 20px from edge
        sw = ind.winfo_screenwidth()
        sh = ind.winfo_screenheight()
        w, h = 160, 48
        ind.geometry(f"{w}x{h}+{sw - w - 20}+{sh - h - 60}")

        # Red border frame
        border = tk.Frame(ind, bg=RECORD_RED, padx=2, pady=2)
        border.pack(fill="both", expand=True)
        inner = tk.Frame(border, bg="#0a0e1a")
        inner.pack(fill="both", expand=True)

        content = tk.Frame(inner, bg="#0a0e1a")
        content.pack(fill="both", expand=True, padx=6, pady=4)

        # Red dot + REC label
        left = tk.Frame(content, bg="#0a0e1a")
        left.pack(side="left", fill="y")
        self._dot_label = tk.Label(left, text="●", font=("Segoe UI", 14),
                                    fg=RECORD_RED, bg="#0a0e1a")
        self._dot_label.pack(side="left", padx=(0, 4))
        tk.Label(left, text="REC", font=("Consolas", 9, "bold"),
                 fg=RECORD_RED, bg="#0a0e1a").pack(side="left")

        # Event count
        self._ind_count_var = tk.StringVar(value="0 events")
        tk.Label(content, textvariable=self._ind_count_var,
                 font=("Consolas", 8), fg=TEXT_DIM, bg="#0a0e1a"
                 ).pack(side="right")

        self._rec_indicator = ind
        self._dot_pulse_state = True
        self._pulse_dot()

    def _pulse_dot(self):
        """Animate the red dot by toggling opacity."""
        if not hasattr(self, '_rec_indicator') or not self._rec_indicator:
            return
        if not self._recording:
            return
        try:
            self._dot_pulse_state = not self._dot_pulse_state
            color = RECORD_RED if self._dot_pulse_state else "#5a0a0a"
            self._dot_label.configure(fg=color)
            # Update event count
            count = self._recorder.event_count if self._recorder else 0
            self._ind_count_var.set(f"{count} events")
            self.root.after(600, self._pulse_dot)
        except Exception:
            pass

    def _hide_recording_indicator(self):
        """Remove the floating recording indicator."""
        if hasattr(self, '_rec_indicator') and self._rec_indicator:
            try:
                self._rec_indicator.destroy()
            except Exception:
                pass
            self._rec_indicator = None

    def _show_countdown(self, seconds: int, on_done: callable):
        """
        Show a large floating countdown overlay (3… 2… 1…) then call on_done.
        The overlay is always-on-top so it's visible over any application.
        """
        overlay = tk.Toplevel(self.root)
        overlay.overrideredirect(True)          # No title bar
        overlay.attributes("-topmost", True)    # Always on top
        overlay.attributes("-alpha", 0.88)      # Slightly transparent
        overlay.configure(bg="#0a0e1a")

        # Centre on screen
        sw = overlay.winfo_screenwidth()
        sh = overlay.winfo_screenheight()
        w, h = 220, 220
        overlay.geometry(f"{w}x{h}+{(sw - w)//2}+{(sh - h)//2}")

        # Border frame
        border = tk.Frame(overlay, bg=RECORD_RED, padx=3, pady=3)
        border.pack(fill="both", expand=True)
        inner = tk.Frame(border, bg="#0a0e1a")
        inner.pack(fill="both", expand=True)

        tk.Label(inner, text="Starting in",
                 font=("Segoe UI", 12), fg=TEXT_DIM, bg="#0a0e1a").pack(pady=(24, 0))

        count_var = tk.StringVar(value=str(seconds))
        count_label = tk.Label(inner, textvariable=count_var,
                               font=("JetBrains Mono", 72, "bold") if False else ("Consolas", 72, "bold"),
                               fg=RECORD_RED, bg="#0a0e1a")
        count_label.pack()

        tk.Label(inner, text="Switch to your app now",
                 font=("Segoe UI", 10), fg=TEXT_DIM, bg="#0a0e1a").pack(pady=(0, 16))

        remaining = [seconds]

        def tick():
            remaining[0] -= 1
            if remaining[0] > 0:
                count_var.set(str(remaining[0]))
                # Flash red → white on each tick
                count_label.configure(fg="#ffffff")
                overlay.after(150, lambda: count_label.configure(fg=RECORD_RED))
                overlay.after(1000, tick)
            else:
                overlay.destroy()
                on_done()

        overlay.after(1000, tick)

    def _start_recording(self):
        # Guard: don't record while a workflow is running (they share mouse/keyboard)
        if self._wf_run_thread and self._wf_run_thread.is_alive():
            messagebox.showwarning(
                "Workflow Running",
                "Please stop the running workflow before starting a macro recording."
            )
            return
        try:
            from macro_recorder import MacroRecorder
        except ImportError:
            messagebox.showerror("Error", "pynput is required for recording.\nRun install.bat first.")
            return

        # Update UI to show countdown state
        self.record_btn.configure(state="disabled")
        self.stop_rec_btn.configure(state="disabled")
        self.rec_status_var.set("Starting in 3 seconds — switch to your app")
        self.rec_status_label.configure(fg="#f59e0b")
        self._set_status("Countdown…")

        def _begin_recording():
            self._recorder = MacroRecorder(
                record_mouse_move=True,
                mouse_move_throttle_ms=100,  # Throttle moves to max 10/sec
                on_event=self._on_macro_event
            )
            self._recorder.start()
            self._recording = True
            self.stop_rec_btn.configure(state="normal", bg=RECORD_RED)
            self.rec_status_var.set("● RECORDING — perform your task now")
            self.rec_status_label.configure(fg="#ff5555")
            self._macro_log_append("Recording started — perform your task...", "info")
            self._set_status("Recording macro…")
            self.root.title("Desktop Automation Agent  ●  RECORDING (F10 to stop)")
            self._show_recording_indicator()  # Show floating red dot

        self._show_countdown(3, _begin_recording)

    def _stop_recording(self):
        if not self._recorder:
            return

        # 1. Signal stop immediately — this is instant and non-blocking.
        #    _recording=False stops new events being captured right away.
        #    The actual listener.stop() calls happen in a background thread
        #    inside recorder.stop(), so the GUI never freezes.
        events = self._recorder.stop()   # Returns immediately
        self._recording = False
        count = len(events)

        # 2. Update UI immediately
        self.record_btn.configure(state="normal")
        self.stop_rec_btn.configure(state="disabled", bg="#555")
        self.rec_status_var.set(f"✓ Recorded {count} events — save it below")
        self.rec_status_label.configure(fg=TEXT_DIM)
        self._macro_log_append(f"Recording stopped — {count} events captured", "success")
        self._set_status(f"Recorded {count} events")
        self._hide_recording_indicator()
        self.root.title("Desktop Automation Agent")
        if count > 0:
            self.play_btn.configure(state="normal")

    def _on_macro_event(self, event):
        """
        Called from the pynput recorder thread for each event.
        IMPORTANT: Never call tkinter directly here — always use root.after().
        Mouse move events are NOT logged (too frequent) to avoid flooding the queue.
        """
        etype = event.get("type", "")
        t = event.get("time", 0)

        # Only log clicks and key presses — skip mouse_move to prevent GUI flooding
        if etype == "mouse_click" and event.get("pressed"):
            msg = f"[{t:.2f}s] Click {event.get('button','left')} at ({event['x']}, {event['y']})"
            self.root.after(0, lambda m=msg: self._macro_log_append(m, "click"))
        elif etype == "key_press":
            key = event.get("key", "")
            msg = f"[{t:.2f}s] Type: {key!r}" if len(key) == 1 else f"[{t:.2f}s] Key: {key}"
            self.root.after(0, lambda m=msg: self._macro_log_append(m, "key"))

        # Update event count only every 5 events to reduce GUI load
        count = self._recorder.event_count if self._recorder else 0
        if count % 5 == 0 or etype in ("mouse_click", "key_press"):
            self.root.after(0, lambda c=count: self.rec_status_var.set(f"● RECORDING — {c} events"))

    def _save_macro(self):
        if not self._recorder or not self._recorder._events:
            messagebox.showwarning("Nothing to save", "Record a macro first.")
            return
        name = self.macro_name_var.get().strip()
        if not name:
            messagebox.showwarning("Name required", "Enter a name for the macro.")
            return
        path = self._recorder.save(name)
        self._macro_log_append(f"Macro saved: {os.path.basename(path)}", "success")
        self._set_status(f"Macro saved: {name}")
        self._refresh_macro_list()

    def _refresh_macro_list(self):
        try:
            from macro_recorder import MacroRecorder
            macros = MacroRecorder.list_macros()
            self.macro_listbox.delete(0, "end")
            for m in macros:
                dur = f"{m['duration']:.1f}s" if m['duration'] else "?"
                self.macro_listbox.insert("end", f"{m['name']}  ({m['event_count']} events, {dur})")
            self._macros_data = macros
        except Exception:
            pass

    def _on_macro_select(self, event):
        sel = self.macro_listbox.curselection()
        if sel and hasattr(self, "_macros_data") and sel[0] < len(self._macros_data):
            m = self._macros_data[sel[0]]
            self.macro_name_var.set(m["name"])

    def _load_selected_macro(self):
        sel = self.macro_listbox.curselection()
        if not sel or not hasattr(self, "_macros_data"):
            messagebox.showinfo("Select a macro", "Click a macro in the list first.")
            return
        m = self._macros_data[sel[0]]
        try:
            from macro_recorder import MacroRecorder
            self._current_macro = MacroRecorder.load(m["path"])
            self._macro_log_append(f"Loaded: {m['name']} ({m['event_count']} events)", "success")
            self.play_btn.configure(state="normal")
            self._set_status(f"Macro loaded: {m['name']}")
        except Exception as e:
            messagebox.showerror("Error", f"Could not load macro:\n{e}")

    def _delete_selected_macro(self):
        sel = self.macro_listbox.curselection()
        if not sel or not hasattr(self, "_macros_data"):
            return
        m = self._macros_data[sel[0]]
        if messagebox.askyesno("Delete", f"Delete macro '{m['name']}'?"):
            try:
                os.remove(m["path"])
                self._refresh_macro_list()
                self._set_status(f"Deleted: {m['name']}")
            except Exception as e:
                messagebox.showerror("Error", str(e))

    def _on_loop_toggle(self):
        """Grey out the Repeat field when loop mode is on."""
        # The repeat entry is in play_settings — disable it when looping
        looping = self.loop_var.get()
        self.loop_count_var.set("" if not looping else "Loop mode active — press F6 to stop")

    def _play_macro(self):
        # Use current_macro if loaded, else use recorder's events
        macro_data = self._current_macro
        if macro_data is None and self._recorder and self._recorder._events:
            macro_data = {"name": "unsaved", "events": self._recorder._events}
        if not macro_data:
            messagebox.showwarning("No macro", "Record or load a macro first.")
            return

        try:
            speed = float(self.speed_var.get())
        except ValueError:
            speed = 1.0

        loop_mode = self.loop_var.get()
        if loop_mode:
            repeat = None  # Infinite
        else:
            try:
                repeat = max(1, int(self.repeat_var.get()))
            except ValueError:
                repeat = 1

        self._macro_stop_event = threading.Event()
        self._loop_count = 0
        self._loop_start_time = __import__('time').time()
        self.play_btn.configure(state="disabled")
        self.stop_play_btn.configure(state="normal")

        if loop_mode:
            self._set_status(f"Looping macro (speed={speed}x) — F6 to stop")
            self._macro_log_append(f"∞ Looping: {macro_data.get('name','?')} at {speed}x speed — press F6 to stop", "info")
            self.loop_count_var.set("Loop 1 running…")
        else:
            self._set_status(f"Playing macro (speed={speed}x, repeat={repeat})…")
            self._macro_log_append(f"Playing: {macro_data.get('name','?')} — speed={speed}x, repeat={repeat}", "info")

        from macro_player import MacroPlayer
        self._player = MacroPlayer()

        def _progress(current, total):
            # Update loop counter display
            if loop_mode and current == 1:
                self._loop_count += 1
                elapsed = __import__('time').time() - self._loop_start_time
                msg = f"Loop {self._loop_count} running  ({elapsed:.0f}s elapsed)"
                self.root.after(0, lambda m=msg: self.loop_count_var.set(m))
                self.root.after(0, lambda m=msg: self._set_status(m))

        def _done(success):
            if loop_mode and not self._macro_stop_event.is_set():
                # Restart immediately for next loop
                self._macro_thread = self._player.play_in_thread(
                    macro_data, speed=speed, repeat=1,
                    stop_event=self._macro_stop_event,
                    progress_callback=_progress,
                    done_callback=_done
                )
                return
            # Stopped or finished
            if loop_mode:
                elapsed = __import__('time').time() - self._loop_start_time
                msg = f"⏹ Loop stopped after {self._loop_count} loops ({elapsed:.0f}s)"
                self.root.after(0, lambda m=msg: self.loop_count_var.set(m))
            else:
                msg = "✓ Macro complete" if success else "⏹ Macro stopped"
            self.root.after(0, lambda: self._macro_log_append(msg, "success" if success else "info"))
            self.root.after(0, lambda: self._set_status(msg))
            self.root.after(0, lambda: (
                self.play_btn.configure(state="normal"),
                self.stop_play_btn.configure(state="disabled")
            ))

        self._macro_thread = self._player.play_in_thread(
            macro_data,
            speed=speed,
            repeat=1 if loop_mode else repeat,
            stop_event=self._macro_stop_event,
            progress_callback=_progress,
            done_callback=_done
        )

    def _stop_playback(self):
        if self._macro_stop_event:
            self._macro_stop_event.set()
        self.stop_play_btn.configure(state="disabled")
        self._set_status("Stopping playback…")
        # Clear loop counter when stopped
        if hasattr(self, 'loop_count_var') and self.loop_var.get():
            self.loop_count_var.set("Stopping…")

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
        for level in ("DEBUG", "WARNING", "ERROR", "SUCCESS"):
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

    def _macro_log_append(self, text, tag="info"):
        self.macro_log.configure(state="normal")
        self.macro_log.insert("end", text + "\n", tag)
        self.macro_log.see("end")
        self.macro_log.configure(state="disabled")

    def _clear_macro_log(self):
        self.macro_log.configure(state="normal")
        self.macro_log.delete("1.0", "end")
        self.macro_log.configure(state="disabled")

    def _set_status(self, message):
        self.status_var.set(message)

    # ── Global Hotkeys ─────────────────────────────────────────────────────────
    def _start_hotkey_listener(self):
        """
        Start a global keyboard listener for F9 (record) and F10 (stop).
        Runs in a daemon thread — works even when the app window is in the background.
        """
        try:
            from pynput import keyboard as kb
        except ImportError:
            logging.warning("pynput not available — global hotkeys disabled")
            return

        self._hotkey_listener = None

        def on_press(key):
            try:
                if key == kb.Key.f9:
                    if not self._recording:
                        self.root.after(0, self._hotkey_start_recording)
                elif key == kb.Key.f10:
                    if self._recording:
                        self.root.after(0, self._hotkey_stop_recording)
                elif key == kb.Key.f5:
                    # F5: play macro
                    self.root.after(0, self._hotkey_play)
                elif key == kb.Key.f6:
                    # F6: stop playback
                    self.root.after(0, self._hotkey_stop_play)
            except Exception:
                pass

        self._hotkey_listener = kb.Listener(on_press=on_press, daemon=True)
        self._hotkey_listener.start()
        logging.info("Global hotkeys active: F9 = Start Recording, F10 = Stop Recording")

    def _hotkey_start_recording(self):
        """Called from main thread when F9 is pressed."""
        # Switch to macro tab so user can see the countdown
        self._switch_tab("macro")
        self._start_recording()

    def _hotkey_stop_recording(self):
        """Called from main thread when F10 is pressed."""
        self._stop_recording()
        self.root.title("Desktop Automation Agent")

    def _hotkey_play(self):
        """Called from main thread when F5 is pressed."""
        self._switch_tab("macro")
        self._play_macro()

    def _hotkey_stop_play(self):
        """Called from main thread when F6 is pressed."""
        self._stop_playback()

    # ── Close ─────────────────────────────────────────────────────────────────
    def _on_close(self):
        # Stop global hotkey listener
        if hasattr(self, '_hotkey_listener') and self._hotkey_listener:
            try:
                self._hotkey_listener.stop()
            except Exception:
                pass
        # Remove floating indicator if visible
        self._hide_recording_indicator()
        if self._recording:
            if not messagebox.askyesno("Quit", "Recording in progress. Stop and quit?"):
                return
            if self._recorder:
                self._recorder.stop()
        if self._player and self._player.is_playing:
            self._macro_stop_event.set()
        self.root.destroy()


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    DesktopAgentApp()
