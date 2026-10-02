"""Headless listener for experiments: receives the four streams, logs the PC arrival time of every device frame and every muxed frame, and prints 1 Hz rates."""
import argparse
import json
import os
import queue
import sys
import threading as th
import time

import numpy as np

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import cfg  # noqa: E402
from tcp_tail_listener import DEVICES, CascadeFrameMux, TcpTailListener, frame_bytes_per_device  # noqa: E402


class Stamper(th.Thread):
    def __init__(self, src, dst, log_path):
        super().__init__(daemon=True)
        self.src, self.dst = src, dst
        self.log = open(log_path, "w")
        self.running = True

    def run(self):
        while self.running:
            try:
                idx, frame = self.src.get(timeout=0.1)
            except queue.Empty:
                continue
            self.log.write("%d,%.6f,%.6f\n" % (idx, time.perf_counter(), time.time()))
            try:
                self.dst.put((idx, frame), block=False)
            except queue.Full:
                pass
        self.log.close()


def main():
    c = cfg.load()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("out_dir")
    ap.add_argument("--loops", type=int, default=c["capture"]["loops"])
    ap.add_argument("--duration", type=float, default=0)
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    fb = frame_bytes_per_device(c["capture"]["samples"], c["capture"]["chirps"], a.loops)
    raw_q, mux_q, listeners, stampers = {}, {}, {}, []
    for dev, port in zip(DEVICES, c["pc"]["ports"]):
        raw_q[dev] = queue.Queue(maxsize=4096)
        mux_q[dev] = queue.Queue(maxsize=4096)
        lst = TcpTailListener(dev, raw_q[dev], fb // 2, (c["pc"]["bind"], port), emit_index=True)
        lst.start()
        listeners[dev] = lst
        st = Stamper(raw_q[dev], mux_q[dev], os.path.join(a.out_dir, "frames_%s.csv" % dev))
        st.start()
        stampers.append(st)
    out = queue.Queue(maxsize=256)
    mux = CascadeFrameMux(mux_q, out, c["capture"]["samples"], c["capture"]["chirps"], a.loops)
    mux.start()
    mlog = open(os.path.join(a.out_dir, "mux.csv"), "w")
    t0 = time.perf_counter()
    last_t, last_bytes = t0, {d: 0 for d in DEVICES}
    rates = {d: [] for d in DEVICES}
    try:
        while True:
            try:
                while True:
                    idx, _ = out.get(timeout=0.05)
                    mlog.write("%d,%.6f,%.6f\n" % (idx, time.perf_counter(), time.time()))
            except queue.Empty:
                pass
            t = time.perf_counter()
            if t - last_t >= 1.0:
                parts = []
                for d in DEVICES:
                    b = listeners[d].stats["bytes"]
                    r = (b - last_bytes[d]) / (t - last_t) / 1e6
                    if b > last_bytes[d]:
                        rates[d].append(r)
                    last_bytes[d] = b
                    parts.append("%s:%6.2fMB/s f=%d" % (d, r, listeners[d].stats["frames"]))
                print("[%7.1fs] %s || mux emitted=%d gaps=%d incomplete=%d" % (t - t0, " | ".join(parts), mux.stats["emitted"], mux.stats["gaps"], mux.stats["incomplete_dropped"]), flush=True)
                last_t = t
            if a.duration and t - t0 >= a.duration:
                break
    except KeyboardInterrupt:
        pass
    finally:
        mux.stop()
        for lst in listeners.values():
            lst.stop()
        time.sleep(0.5)
        for st in stampers:
            st.running = False
        summary = dict(loops=a.loops, frame_bytes_per_device=fb, run_seconds=time.perf_counter() - t0,
                       per_device={d: dict(listeners[d].stats, mean_rate_MBps=(float(np.mean(rates[d])) if rates[d] else 0.0)) for d in DEVICES},
                       mux=mux.stats)
        json.dump(summary, open(os.path.join(a.out_dir, "listener.json"), "w"), indent=1, default=str)
        mlog.close()
        print("# SUMMARY " + json.dumps(summary, default=str), flush=True)


if __name__ == "__main__":
    main()
