"""
Macro Recorder Worker — runs as a SEPARATE PROCESS from the GUI.

This script has NO tkinter dependency. It runs pynput listeners,
writes events to an output JSON file, and stops when a stop-signal
file appears. The GUI process never touches pynput directly.

Usage (called by app.py via subprocess.Popen):
    python recorder_worker.py <output_file> <stop_signal_file> [throttle_ms]

Protocol:
    - Writes events to <output_file> as a JSON array (updated live)
    - Polls for <stop_signal_file> every 100ms; stops when it appears
    - Prints "READY" to stdout when listeners are active
    - Prints "STOPPED:<count>" to stdout when done
    - Exits with code 0 on clean stop, 1 on error
"""

import sys
import os
import json
import time
import threading

def main():
    if len(sys.argv) < 3:
        print("Usage: recorder_worker.py <output_file> <stop_signal_file> [throttle_ms]")
        sys.exit(1)

    output_file   = sys.argv[1]
    stop_signal   = sys.argv[2]
    throttle_ms   = float(sys.argv[3]) if len(sys.argv) > 3 else 80.0

    # Redirect stderr to devnull so Xlib/pynput warnings don't pollute stdout
    devnull = open(os.devnull, 'w')
    sys.stderr = devnull
    os.dup2(devnull.fileno(), 2)  # Also redirect fd 2

    try:
        from pynput import mouse, keyboard
    except ImportError:
        print("ERROR: pynput not installed", flush=True)
        sys.exit(1)

    events = []
    lock = threading.Lock()
    start_time = time.time()
    last_move_time = [0.0]
    running = [True]

    def elapsed():
        return round(time.time() - start_time, 4)

    def record(event):
        with lock:
            if running[0]:
                events.append(event)

    def on_move(x, y):
        now = time.time() * 1000
        if now - last_move_time[0] < throttle_ms:
            return
        last_move_time[0] = now
        record({"type": "mouse_move", "x": x, "y": y, "time": elapsed()})

    def on_click(x, y, button, pressed):
        record({"type": "mouse_click", "x": x, "y": y,
                "button": str(button).replace("Button.", ""),
                "pressed": pressed, "time": elapsed()})

    def on_scroll(x, y, dx, dy):
        record({"type": "mouse_scroll", "x": x, "y": y,
                "dx": dx, "dy": dy, "time": elapsed()})

    def key_name(key):
        try:
            return key.char
        except AttributeError:
            return str(key).replace("Key.", "")

    def on_key_press(key):
        record({"type": "key_press", "key": key_name(key), "time": elapsed()})

    def on_key_release(key):
        record({"type": "key_release", "key": key_name(key), "time": elapsed()})

    # Start listeners
    ml = mouse.Listener(on_move=on_move, on_click=on_click,
                        on_scroll=on_scroll, daemon=True)
    kl = keyboard.Listener(on_press=on_key_press, on_release=on_key_release,
                           suppress=False, daemon=True)
    ml.start()
    kl.start()

    # Signal GUI that we are ready
    print("READY", flush=True)

    # Poll for stop signal
    while True:
        time.sleep(0.1)
        if os.path.exists(stop_signal):
            break

    # Stop recording
    running[0] = False

    # Stop listeners (safe here — we are NOT in a tkinter thread)
    try:
        ml.stop()
    except Exception:
        pass
    try:
        kl.stop()
    except Exception:
        pass

    # Write final events to output file
    with lock:
        final_events = list(events)

    with open(output_file, "w") as f:
        json.dump(final_events, f)

    print(f"STOPPED:{len(final_events)}", flush=True)
    sys.exit(0)


if __name__ == "__main__":
    main()
