"""
Desktop Automation Agent - Launcher
Starts the GUI. Shows any startup errors in a popup so they don't disappear.
"""
import os
import sys
import glob
import traceback
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
APP  = os.path.join(HERE, "app.py")


def find_python():
    path_file = os.path.join(HERE, "python_path.txt")
    if os.path.isfile(path_file):
        saved = open(path_file).read().strip()
        if os.path.isfile(saved):
            return saved
    if sys.executable and os.path.isfile(sys.executable):
        return sys.executable
    local = os.environ.get("LOCALAPPDATA", "")
    for v in ["314","313","312","311","310","39","38"]:
        for d in [
            os.path.join(local, "Programs", "Python", f"Python{v}", "python.exe"),
            os.path.join(local, "Programs", "Python", f"pythoncore-{v}-64", "python.exe"),
            os.path.join(local, "Programs", "Python", f"pythoncore-{v}-32", "python.exe"),
        ]:
            if os.path.isfile(d):
                return d
    base = os.path.join(local, "Programs", "Python")
    if os.path.isdir(base):
        hits = glob.glob(os.path.join(base, "*", "python.exe"))
        if hits:
            return hits[0]
    return None


def show_error(title, message):
    """Show error in a tkinter popup — always works even if other packages missing."""
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, message)
        root.destroy()
    except Exception:
        # Last resort — keep console open
        print(f"\n{'='*60}")
        print(f"ERROR: {title}")
        print(f"{'='*60}")
        print(message)
        print(f"{'='*60}\n")
        input("Press Enter to exit...")


def main():
    python = find_python()
    if not python:
        show_error("Python Not Found",
                   "Python not found.\n\nPlease run install.bat first.")
        sys.exit(1)

    if not os.path.isfile(APP):
        show_error("File Not Found",
                   f"app.py not found at:\n{APP}\n\nMake sure you extracted the full zip.")
        sys.exit(1)

    os.chdir(HERE)

    # Run app.py and capture any startup error
    result = subprocess.run(
        [python, APP],
        cwd=HERE
    )

    if result.returncode != 0:
        # Read the log for the actual error
        log_path = os.path.join(HERE, "logs", "desktop_agent.log")
        log_tail = ""
        if os.path.isfile(log_path):
            lines = open(log_path, encoding="utf-8", errors="ignore").readlines()
            log_tail = "".join(lines[-20:])

        show_error(
            "App Failed to Start",
            f"The application crashed on startup.\n\n"
            f"Most likely cause: a required package is not installed.\n\n"
            f"Fix: run install.bat again.\n\n"
            f"Last log lines:\n{log_tail or '(no log found)'}"
        )


if __name__ == "__main__":
    main()
