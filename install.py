"""
Desktop Automation Agent — Installer
Run this once to install all required packages.

Usage:
  Windows: double-click install.bat  (or: python install.py)
  Mac/Linux: python3 install.py
"""
import os
import sys
import subprocess
import glob

HERE = os.path.dirname(os.path.abspath(__file__))

def find_python():
    """Return the path to a working Python 3.8+ executable."""
    # 1. The current interpreter (this script is already running with it)
    exe = sys.executable
    if exe and os.path.exists(exe):
        return exe

    # 2. Common Windows install paths
    local = os.environ.get("LOCALAPPDATA", "")
    prog  = os.environ.get("ProgramFiles", "")
    prog86 = os.environ.get("ProgramFiles(x86)", "")

    candidates = []
    for version in ["314","313","312","311","310","39","38"]:
        candidates += [
            os.path.join(local,  "Programs", "Python", f"Python{version}",          "python.exe"),
            os.path.join(local,  "Programs", "Python", f"pythoncore-{version}-64",  "python.exe"),
            os.path.join(local,  "Programs", "Python", f"pythoncore-{version}-32",  "python.exe"),
            os.path.join(prog,   f"Python{version}", "python.exe"),
            os.path.join(prog86, f"Python{version}", "python.exe"),
            f"C:\\Python{version}\\python.exe",
        ]

    # Also glob everything under AppData\Local\Programs\Python\
    base = os.path.join(local, "Programs", "Python")
    if os.path.isdir(base):
        candidates += glob.glob(os.path.join(base, "*", "python.exe"))

    for path in candidates:
        if os.path.isfile(path):
            return path

    return None


def run(cmd, **kwargs):
    """Run a command, printing it first."""
    print("  >", " ".join(str(c) for c in cmd))
    return subprocess.call(cmd, **kwargs)


def main():
    print()
    print("=" * 60)
    print("  Desktop Automation Agent — Installer")
    print("=" * 60)
    print()

    python = find_python()
    if not python:
        print("ERROR: Could not find Python on this computer.")
        print()
        print("Please install Python from: https://www.python.org/downloads/")
        print("During install, check 'Add Python to PATH'")
        print()
        input("Press Enter to exit...")
        sys.exit(1)

    print(f"[OK] Python found: {python}")
    run([python, "--version"])
    print()

    # Save path for the launcher
    path_file = os.path.join(HERE, "python_path.txt")
    with open(path_file, "w") as f:
        f.write(python)
    print(f"[OK] Python path saved to: {path_file}")
    print()

    # Upgrade pip
    print("Upgrading pip...")
    run([python, "-m", "pip", "install", "--upgrade", "pip", "--quiet"])
    print("[OK] pip ready.")
    print()

    # Install requirements
    req = os.path.join(HERE, "requirements.txt")
    print("Installing packages (1-3 minutes on first run)...")
    print()
    result = run([python, "-m", "pip", "install", "-r", req])

    if result != 0:
        print()
        print("ERROR: Package installation failed.")
        print("Try running this script as Administrator.")
        input("Press Enter to exit...")
        sys.exit(1)

    print()
    print("[OK] All packages installed.")
    print()
    print("=" * 60)
    print("  Installation Complete!")
    print("=" * 60)
    print()
    print("To open the app, double-click:  Run Desktop Agent.bat")
    print("Or run:  python launch.py")
    print()
    input("Press Enter to close...")


if __name__ == "__main__":
    main()
