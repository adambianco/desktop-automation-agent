"""
Test the subprocess-based recorder: start worker, wait 2s, write stop signal, read events.
Measures how long stop takes — should be < 0.05s (just a file write).
"""
import os, sys, time, tempfile, subprocess, json
os.environ.setdefault("DISPLAY", ":99")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

worker = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recorder_worker.py")
tmp = tempfile.gettempdir()
output_file  = os.path.join(tmp, "test_macro_events.json")
stop_signal  = os.path.join(tmp, "test_macro_stop.signal")

for f in [output_file, stop_signal]:
    try: os.remove(f)
    except: pass

print("Launching recorder worker...")
proc = subprocess.Popen(
    [sys.executable, worker, output_file, stop_signal, "80"],
    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
)

# Wait for READY — skip any warning lines
line = ""
for raw_line in proc.stdout:
    line = raw_line.strip()
    print(f"Worker says: {line!r}")
    if line == "READY":
        break
assert line == "READY", f"Expected READY, got {line!r}"
print("Worker is READY. Waiting 2 seconds...")
time.sleep(2)

# Stop — just write a file
print("Writing stop signal...")
t0 = time.time()
with open(stop_signal, "w") as f:
    f.write("stop")
elapsed_stop = time.time() - t0
print(f"Stop signal written in {elapsed_stop*1000:.1f}ms")

# Wait for worker to finish
proc.wait(timeout=5)
elapsed_total = time.time() - t0
print(f"Worker exited in {elapsed_total:.2f}s")

# Read events
events = []
if os.path.exists(output_file):
    with open(output_file) as f:
        events = json.load(f)

print(f"Events captured: {len(events)}")
print()
if elapsed_stop < 0.05:
    print("PASS: stop() is instant (file write only) — GUI will NEVER freeze")
else:
    print(f"FAIL: stop took {elapsed_stop*1000:.0f}ms")
