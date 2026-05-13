"""
Test the full GUI record/stop cycle to find where the freeze happens.
Auto-starts recording after 1s, auto-stops after 3s, measures responsiveness.
"""
import os, sys, time, threading
os.environ["DISPLAY"] = ":99"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tkinter as tk
from tkinter import messagebox

results = []

def log(msg):
    t = time.time() - start
    results.append(f"[{t:.3f}s] {msg}")
    print(f"[{t:.3f}s] {msg}")

start = time.time()

# Build minimal GUI
root = tk.Tk()
root.title("Test")
root.geometry("300x200")

status_var = tk.StringVar(value="Ready")
tk.Label(root, textvariable=status_var, font=("Consolas", 11)).pack(pady=20)

recorder = None
recording = False

def start_recording():
    global recorder, recording
    log("start_recording() called")
    from macro_recorder import MacroRecorder
    recorder = MacroRecorder(record_mouse_move=False)
    recorder.start()
    recording = True
    status_var.set("RECORDING")
    log("start_recording() done")

def stop_recording():
    global recorder, recording
    log("stop_recording() called — about to call recorder.stop()")
    t0 = time.time()
    events = recorder.stop()
    elapsed = time.time() - t0
    recording = False
    log(f"recorder.stop() returned in {elapsed:.3f}s with {len(events)} events")
    status_var.set(f"Stopped — {len(events)} events")
    log("UI updated after stop")

def run_test():
    log("Test starting")
    time.sleep(1)
    log("Scheduling start_recording on main thread")
    root.after(0, start_recording)
    time.sleep(3)
    log("Scheduling stop_recording on main thread")
    root.after(0, stop_recording)
    time.sleep(2)
    log("Test complete — closing")
    root.after(0, root.quit)

t = threading.Thread(target=run_test, daemon=True)
t.start()

log("mainloop starting")
root.mainloop()
log("mainloop ended")

print("\n=== RESULTS ===")
for r in results:
    print(r)
