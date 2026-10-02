"""Converts a TDA capture directory (<dev>_NNNN_data.bin x4, on the PC) into a replayable recording captures/<name>/."""
import argparse
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cfg  # noqa: E402
from parse_idx import parse_idx  # noqa: E402
from tcp_tail_listener import CAPTURES, DEVICES  # noqa: E402


def main():
    c = cfg.load()["capture"]
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("tda_dir")
    ap.add_argument("name")
    ap.add_argument("--samples", type=int, default=c["samples"])
    ap.add_argument("--chirps", type=int, default=c["chirps"])
    ap.add_argument("--loops", type=int, default=c["loops"], help="loops per frame of the capture")
    ap.add_argument("--slice-loops", type=int, default=0, help="keep only the first N loops of each frame (0 = all)")
    ap.add_argument("--period-ms", type=float, default=None, help="frame period (default: from the master idx)")
    ap.add_argument("--file-idx", type=int, default=0)
    a = ap.parse_args()
    fb = a.samples * a.chirps * a.loops * 4 * 2 * 2
    idxp = os.path.join(a.tda_dir, "master_%04d_idx.bin" % a.file_idx)
    ts = None
    if os.path.exists(idxp):
        _, recs = parse_idx(idxp)
        n = len(recs)
        ts = recs["timestamp_us"].astype(np.int64) / 1e6
        if a.period_ms is None and n > 1:
            a.period_ms = float(np.median(np.diff(ts)) * 1e3)
    else:
        n = os.path.getsize(os.path.join(a.tda_dir, "master_%04d_data.bin" % a.file_idx)) // fb
    out_loops = a.slice_loops or a.loops
    fb_out = a.samples * a.chirps * out_loops * 4 * 2 * 2
    d = os.path.join(CAPTURES, a.name)
    os.makedirs(d, exist_ok=True)
    files = [open(os.path.join(a.tda_dir, "%s_%04d_data.bin" % (dev, a.file_idx)), "rb") for dev in DEVICES]
    fbin = open(os.path.join(d, "frames.bin"), "wb")
    fcsv = open(os.path.join(d, "frames.csv"), "w")
    fcsv.write("frame_idx,t_pc_perf,t_pc_wall,byte_offset\n")
    t0 = time.time()
    off = 0
    for k in range(n):
        t_rel = (ts[k] - ts[0]) if ts is not None else k * (a.period_ms or 100) / 1e3
        for f in files:
            f.seek(k * fb)
            raw = np.frombuffer(f.read(fb), dtype="<i2")
            if len(raw) < fb // 2:
                break
            if a.slice_loops:
                raw = raw.reshape(a.loops, -1)[:a.slice_loops].reshape(-1)
            fbin.write(raw.tobytes())
        fcsv.write("%d,%.6f,%.6f,%d\n" % (k, t_rel, t0 + t_rel, off))
        off += 4 * fb_out
    for f in files:
        f.close()
    fbin.close(); fcsv.close()
    config = dict(name=a.name, samples=a.samples, chirps=a.chirps, loops=out_loops, frame_bytes_per_device=fb_out,
                  frame_bytes_total=4 * fb_out, devices=list(DEVICES), period_ms=a.period_ms, tag=None, start_wall=t0,
                  start_iso=time.strftime("%Y-%m-%d %H:%M:%S"), frames_recorded=n, bytes=off,
                  notes="converted from %s (loops %d%s)" % (a.tda_dir, a.loops, ", sliced to %d" % a.slice_loops if a.slice_loops else ""),
                  layout="per frame: master|slave1|slave2|slave3 raw int16 blocks, each as in <dev>_NNNN_data.bin")
    json.dump(config, open(os.path.join(d, "config.json"), "w"), indent=1)
    print("wrote %s: %d frames x %d B (%.1f MB), period %s ms, loops %d" % (d, n, 4 * fb_out, off / 1e6, a.period_ms, out_loops))


if __name__ == "__main__":
    main()
