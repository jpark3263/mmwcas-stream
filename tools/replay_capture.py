"""Replays a recording (captures/<name>/) through the frame mux offline and prints its statistics."""
import argparse
import json
import os
import queue
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tcp_tail_listener import CAPTURES, DEVICES, CascadeFrameMux, ReplaySource  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("name")
    ap.add_argument("--speed", type=float, default=0.0, help="1 = recorded pacing, 0 = as fast as possible")
    ap.add_argument("--count", type=int, default=0, help="replay only the first N frames (0 = all)")
    a = ap.parse_args()
    c = json.load(open(os.path.join(CAPTURES, a.name, "config.json")))
    print("recording %s: %s" % (a.name, json.dumps({k: c[k] for k in ("samples", "chirps", "loops", "frame_bytes_per_device", "period_ms", "frames_recorded", "start_iso") if k in c})))
    queues = {d: queue.Queue(maxsize=4096) for d in DEVICES}
    out = queue.Queue(maxsize=4096)
    mux = CascadeFrameMux(queues, out, c["samples"], c["chirps"], c["loops"])
    mux.start()
    src = ReplaySource(a.name, queues, speed=a.speed, count=a.count)
    t0 = time.perf_counter()
    src.start()
    n = 0

    def drain():
        nonlocal n
        while True:
            try:
                out.get_nowait()
            except queue.Empty:
                return
            n += 1
    while src.is_alive() or any(not q.empty() for q in queues.values()):
        time.sleep(0.01)
        drain()
    time.sleep(0.3)
    drain()
    mux.stop()
    dt = time.perf_counter() - t0
    print("muxed %d frames in %.2f s (%.0f fps); mux stats %s" % (n, dt, n / dt if dt else 0, mux.stats))


if __name__ == "__main__":
    main()
