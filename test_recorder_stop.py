"""
Test: measure how long MacroRecorder.stop() takes.
If it blocks, it will take > 1 second.
If the fix works, it should return in < 0.1 seconds.
"""
import os, sys, time, threading
os.environ.setdefault("DISPLAY", ":99")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from macro_recorder import MacroRecorder

print("Starting recorder...")
rec = MacroRecorder(record_mouse_move=False)
rec.start()
print("Recording for 2 seconds...")
time.sleep(2)

print("Calling stop()...")
t0 = time.time()
events = rec.stop()
elapsed = time.time() - t0

print(f"stop() returned in {elapsed:.3f}s with {len(events)} events")
if elapsed < 0.5:
    print("PASS: stop() is non-blocking")
else:
    print(f"FAIL: stop() blocked for {elapsed:.3f}s — still freezing")

# Wait for background cleanup
time.sleep(1)
print("Done.")
